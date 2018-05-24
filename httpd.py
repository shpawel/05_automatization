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
from collections import OrderedDict

logger = logging.getLogger(__name__)


LOG_FORMAT = '%(levelname) -5s %(asctime)s %(name) -10s %(funcName) -20s %(lineno) -3d: %(message)s'
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
            self.bind()
            self.listen()
            self._sock.setblocking(0)
        except socket.error as e:
            raise HTTPDException(e)

    def disconnect(self):
        """
        Завершение работы

        :return:
        """

        try:
            logger.info('Закрытие сокета')
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
        self._sock.bind(self._server_address)
        logging.info('Связывание %s', str(self._server_address))

    def listen(self):
        """
        Старт прослушивания входящщих сообщений

        :return:
        """
        self._sock.listen(1)
        self._sock.settimeout(self._timeout)
        logging.info('Старт прослушивания %s ', str(self._sock.getsockname()))

    def run(self):
        """
        Обработка входящих сообщений

        :return:
        """
        try:
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
                            logger.info('Получение данных из %s', r.getpeername())
                            messages[r].put(data)
                            if r not in outputs:
                                outputs.append(r)
                        else:
                            logger.error('Отсутствуют данные в %s. Закрытие.', r.getpeername())
                            if r in outputs:
                                outputs.remove(r)
                            inputs.remove(r)
                            r.close()
                            del messages[r]

                for w in writable:
                    try:
                        next_message = messages[w].get_nowait()
                    except Queue.Empty:
                        logger.error("Очередь сообщений для %s пуста", w.getpeername())
                        outputs.remove(w)
                    except Exception as e:
                        logger.exception(str(e))
                    else:
                        logging.info('Седущее сообщение %s', next_message.replace('\r\n', ' '))
                        revert_message = self.parse_message(next_message)
                        logger.info("Отправка обратного сообщения %s", revert_message.replace('\r\n', ' '))
                        w.sendall(revert_message)

                for e in exceptional:
                    logger.exception('handling exceptional condition for %s', e.getpeername())
                    inputs.remove(e)
                    if e in outputs:
                        outputs.remove(e)
                    e.close()
                    del messages[e]
        finally:
            self.stop()

    def run_simple(self):
        try:
            while True:
                connection, address = self._sock.accept()
                try:
                    connection.setblocking(0)
                    logging.info('Получение данные из %s', address)
                    data = self.read_data(connection)
                    logging.info('Данные получены: %s', data)
                    revert_message = self.parse_message(data)
                    logging.info('Сформировано обратное сообщение')
                    connection.sendall(revert_message)
                    logging.info('Обратное сообщение отправлено')
                finally:
                    connection.close()
        finally:
            self.disconnect()

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
        end_rnrn = b'\r\n\r\n'
        end_nn = b'\n\n'

        request_data = b''
        try:
            while True:
                try:
                    temp = connection.recv(1024)
                except Exception as e:
                    logger.exception(e)
                    break
                else:
                    if bool(temp):
                        request_data += temp
                    else:
                        break
        except Exception as e:
            logger.exception(e)
            pass
        finally:
            if end_rnrn in request_data or end_nn in request_data:
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
                                          status='405 Method Not Allowed',
                                          data='Method Not Allowed',
                                          type_data=b'text/plain')
        else:
            path = address
            #  Удаление якоря
            if '#' in path:
                path, fragment = path.split('#', 1)
            #  Удаление параметров
            if '?' in path:
                path, param = path.split('?', 1)
            #  Нормализация адреса
            if '%' in path:
                fragments_of_path = path.split('%')
                normalize_fragments_of_path = [fragments_of_path[0], ]
                for symbol in fragments_of_path[1:]:
                    normalize_fragments_of_path.append(symbol[:2].decode('hex'))
                    normalize_fragments_of_path.append(symbol[2:])
                path = ''.join(normalize_fragments_of_path)
            logging.info('PATH: %s', path)
            status, data, type_data = self.get_data(path=path)
            message = self.parse_response(method=method,
                                          status=status,
                                          data=data,
                                          type_data=type_data)
        return message

    def parse_header_response(self, method, status, data, type_data='text/plain'):
        """
        Формирование заголовков ответного сообщения

        :param str|unicode method: тип HTTP-запроса
        :param str|unicode status: статус ответа
        :param str|unicode data: передаваемые данные
        :param str|unicode type_data: тип передаваемых данных
        :return: ответное сообщение
        :rtype: bytes
        """
        status_line = 'HTTP/1.1 {}\r\n'.format(status)
        headers = OrderedDict()
        headers['Accept'] = '*/*'
        headers['Accept-Encoding'] = '*'
        headers['Connection'] = 'close'
        headers['Server'] = 'HTTPD 1/.0'
        headers['Allow'] = 'GET, HEAD'
        headers['Content-Length'] = len(data)
        headers['Content-Type'] = type_data
        headers['Date'] = time.strftime('%H:%M:%S %d.%m.%Y')

        headers_str = '\r\n'.join(['{}: {}'.format(key, headers[key]) for key in headers.iterkeys()])
        headers_str = status_line + headers_str + '\r\n\r\n'
        return headers_str.encode('utf-8')

    def parse_response(self, method, status, data, type_data=b'text/plain'):
        """
        Формирование ответного сообщения

        :param str|unicode method: тип HTTP-запроса
        :param str|unicode status: статус ответа
        :param bytes data: передаваемые данные
        :param str|unicode type_data: тип передаваемых данных
        :return: ответное сообщение
        :rtype: bytes
        """
        response1 = self.parse_header_response(method=method, status=status, data=data, type_data=type_data)
        if method != 'HEAD':
            response1 += data
        return response1

    def get_data(self, path):
        """
        Получение запрашиваемых данных

        :param str|unicode method: метод запроса сообщения
        :param str|unicode path: путь к запрашиваемому файлу или директории
        :return: статус, данные, тип передаваемых данных
        :rtype: tuple([str], [str], [bytes])
        """
        _path = os.path.abspath(path).strip('/')
        source = os.path.abspath(os.path.join(self._root, _path))

        if os.path.isdir(source):
            source = os.path.join(source, 'index.html')
        if os.path.exists(source):
            data = open(source, mode='rb').read()
            content_type = mimetypes.guess_type(source)[0]
            status = '200 OK'
        else:
            data = b'Not Found'
            content_type = 'text/plain'
            status = '404 Not Found'
        return status, data, content_type

    def __call__(self, *args, **kwargs):
        self.run()
        # self.run_simple()


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
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    main()
