import sys
from aioquant import quant
from aioquant.utils import logger

def main():
    from aioquant.configure import config
    from aioquant.event import EventConfig

    server_id = "vm226274"
    params = {
        "para": config.para
    }
    EventConfig(server_id, params).publish()
    logger.info("update config successfully...")
    quant.stop()

if __name__ == "__main__":
    config_file = sys.argv[1]
    quant.start(config_file, main)
