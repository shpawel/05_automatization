#!/usr/bin/python2
# -*- coding: utf-8 -*-
import logging
from httpd import LOG_FORMAT, DOCUMENT_ROOT, HTTPD, IP, PORT

logger = logging.getLogger(__name__)


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

    try:
        server = HTTPD(**params)
        server.run_simple()
    except Exception as e:
        logger.exception(str(e))
    except KeyboardInterrupt:
        exit(0)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    main()
