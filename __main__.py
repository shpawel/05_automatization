import logging
from httpd import LOG_FORMAT, main as httpd_main

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)

if __name__ == "__main__":
    httpd_main()
