#!/usr/bin/python2
# -*- coding: utf-8 -*-
import logging
import mimetypes
import os
import re
import select
import socket
import time
import threading
import Queue
from urlparse import urlparse, unquote

logger = logging.getLogger(__name__)


LOG_FORMAT = '%(levelname) -10s %(asctime)s %(name) -30s %(funcName) -35s %(lineno) -5d: %(message)s'
IP = 'localhost'
PORT = 80
ADDR = (IP, PORT)
DOCUMENT_ROOT = os.path.abspath(os.path.join(os.path.curdir, 'tests'))

RE_HEAD = re.compile(r'^(?P<method>\w*) (?P<address>.*) (?P<protocol>HTTP\/\d+\.\d+)$')


class HTTPDException(Exception):
    pass


class HTTPD(object):
    def __init__(self, **kwargs):
        """
        Инициализация нового объекта сервера

        :param str|int kwargs: параметры запуска сервера
        :key host: адрес сервера
        :key port: порт сервера
        :key timeout: время ожидания ответа
        :key root: корневая директория
        """

        self._server_address = (kwargs.pop('host', None) or IP, kwargs.pop('port', None) or PORT)
        self._timeout = kwargs.pop('timeout', None) or float(10.0)
        self._root = kwargs.pop('root', DOCUMENT_ROOT)
        self._sock = None
        self.connect()

    def connect(self):
        """
        Объявление нового сокета

        :return:
        """
        if self._sock:
            self.disconnect()

        try:
            self._sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            self._sock.setblocking(0)
            self.bind()
            self.listen()
        except socket.error as e:
            raise HTTPDException(e)

    def disconnect(self):
        """
        Завершение работы

        :return:
        """

        try:
            logger.info(self._sock)
            self._sock.shutdown(socket.SHUT_WR)
        except socket.error:
            pass
        self._sock.close()
        self._sock = None

    def bind(self):
        """
        Соединение объекта сокета с адресом:портом

        :return:
        """
        self._sock.bind(ADDR)
        logging.info('Bind %s', str(ADDR))

    def listen(self):
        """
        Старт прослушивания входящщих сообщений

        :return:
        """
        self._sock.listen(1)
        self._sock.settimeout(self._timeout)
        logging.info('Listen %s ', str(self._sock.getsockname()))

    def run(self):
        """
        Обработка входящих сообщений

        :return:
        """
        inputs = [self._sock]
        outputs = []
        messages = {}
        while inputs:
            readable, writable, exceptional = select.select(inputs, outputs, inputs, self._timeout)

            for r in readable:
                if r is self._sock:
                    conn, address = r.accept()
                    conn.setblocking(0)
                    inputs.append(conn)
                    messages[conn] = Queue.Queue()
                else:
                    data = self.read_data(r)
                    if data:
                        logger.info('Received message from %s', r.getpeername())
                        messages[r].put(data)
                        if r not in outputs:
                            outputs.append(r)
                    else:
                        logger.error('Empty data in %s. Closing.', r.getpeername())
                        if r in outputs:
                            outputs.remove(r)
                        inputs.remove(r)
                        r.close()
                        del messages[r]

            for w in writable:
                try:
                    next_message = messages[w].get_nowait()
                except Queue.Empty:
                    logger.error("Output queue for %s is empty", w.getpeername())
                    outputs.remove(w)
                except Exception as e:
                    logger.exception(str(e))
                else:
                    logging.info('Next message %s', next_message.replace('\r\n', ' '))
                    revert_message = self.parse_message(next_message)
                    logger.info("Send message %s", revert_message.replace('\r\n', ' '))
                    w.sendall(revert_message)

            for e in exceptional:
                logger.exception('handling exceptional condition for %s', e.getpeername())
                inputs.remove(e)
                if e in outputs:
                    outputs.remove(e)
                e.close()
                del messages[e]

    def stop(self):
        """
        Остановка работы сервера

        :return:
        """
        self.disconnect()

    def read_data(self, connection):
        """
        Чтение данных из сокета

        :param socket._socketobject connection: объек подключения
        :return: полуенные данные
        :rtype: bytes
        """
        end_nrn = b'\r\n\r\n'

        request_data = b''

        while end_nrn not in request_data:
            try:
                temp = connection.recv(1024)
            except Exception as e:
                logger.exception(str(e))
            else:
                if not bool(temp):
                    break
                else:
                    request_data += temp

        return request_data

    def parse_message(self, message):
        """
        Парсинг очередного сообщения

        :param bytes message: полученное сообщение
        :return: обратное сообщения для клиента
        :rtype: bytes
        """
        u_message = message.decode("utf-8")

        info = u_message.split("\r\n", 1)[0]
        logging.info(info)
        macth = RE_HEAD.match(info)
        if macth:
            method = macth.group('method')
            address = macth.group('address')
            protocol = macth.group('protocol')
        else:
            return b'Requies is not valid'

        if method not in ['HEAD', 'GET']:
            message = self.parse_response(method=method,
                                          status=b'405 Method Not Allowed',
                                          data=b'Method Not Allowed',
                                          type_data=b'text/plain')
        else:
            p = urlparse(address)
            u = unquote(p.path)
            logging.info('URL %s', str(u))
            status, data, type_data = self.get_data(path=u)
            message = self.parse_response(method=method,
                                          status=status,
                                          data=data,
                                          type_data=type_data)
        return message

    def parse_response(self, method, status, data, type_data=b'text/plain'):
        """
        Формирование ответного сообщения

        :param str|unicode method: тип HTTP-запроса
        :param str|unicode status: статус ответа
        :param str|unicode data: передаваемые данные
        :param str|unicode type_data: тип передаваемых данных
        :return: ответное сообщение
        :rtype: bytes
        """
        response = b''
        response += b'HTTP/1.1 ' + status.encode('utf-8') + b'\r\n'
        response += b'Accept: */*' + '\r\n'
        response += b'Accept-Encoding: *' + '\r\n'
        response += b'Connection: keep alive' + b'\r\n'
        response += b'Server: HTTPD 1/.0' + '\r\n'
        response += b'Allow: GET, HEAD' + b'\r\n'
        response += b'Content-Length: ' + bytes(len(data)) + b'\r\n'
        response += b'Content-Type: ' + type_data.encode('utf-8') + b'\r\n'
        response += b'Date: ' + time.strftime('%H:%M:%S %d.%m.%Y') + '\r\n'
        response += b'\r\n'
        if method != 'HEAD':
            response += data
        return response

    def get_data(self, path):
        """
        Получение запрашиваемых данных

        :param str|unicode method: метод запроса сообщения
        :param str|unicode path: путь к запрашиваемому файлу или директории
        :return: статус, данные, тип передаваемых данных
        :rtype: tuple([bytes], [bytes], [bytes])
        """
        _path = os.path.abspath(path).strip('/')
        source = os.path.abspath(os.path.join(self._root, _path))

        if os.path.isdir(source):
            source = os.path.join(source, 'index.html')
        if os.path.exists(source):
            data = open(source, mode='rb').read()
            content_type = mimetypes.guess_type(source)[0]
            status = "200 OK"
        else:
            data = b'Not Found'
            content_type = 'text/plain'
            status = '404 Not Found'
        return status, data, content_type

    def __call__(self, *args, **kwargs):
        self.run()


def main():
    import argparse  # noqa

    parser = argparse.ArgumentParser()
    parser.add_argument('--host',
                        help='Адрес сервера',
                        default=IP,
                        type=str)
    parser.add_argument('--port',
                        help='Порт сервера',
                        default=PORT,
                        type=int)
    parser.add_argument('-w', '--workers',
                        help='Число создаваемых потоков',
                        default=4,
                        type=int)
    parser.add_argument('-t', '--timeout',
                        help='Таймаут ожидания ответа',
                        default=60.0,
                        type=float)
    parser.add_argument('-r', '--root',
                        help='Директория по умолчанию',
                        default=DOCUMENT_ROOT)

    args = parser.parse_args()
    params = dict(
        host=args.host,
        port=args.port,
        root=args.root,
        workers=args.workers,
        timeout=args.timeout
    )

    pool = []
    for i in range(args.workers):
        _th = threading.Thread(target=HTTPD(**params))
        pool.append(_th)

    try:
        for _th in pool:
            _th.start()

        for _th in pool:
            _th.join()
    except Exception as e:
        logger.exception(str(e))
    except KeyboardInterrupt:
        exit(0)


if __name__ == '__main__':
    logging.basicConfig(level=logging.ERROR, format=LOG_FORMAT)
    main()
