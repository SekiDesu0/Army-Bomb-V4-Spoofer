import asyncio
import logging
import os
import sys

from gui import ArmyBombGUI


def setup_logging():
    log_dir = os.path.dirname(os.path.abspath(__file__))
    log_file = os.path.join(log_dir, "army_bomb_controller.log")

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-7s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    logging.getLogger("bleak").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    logging.info("=== Army Bomb Controller started ===")


def main():
    setup_logging()

    gui = ArmyBombGUI()

    async def asyncio_loop():
        while True:
            try:
                gui.root.update()
            except Exception:
                logging.exception("Fatal error in GUI event loop")
                break
            await asyncio.sleep(0)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.create_task(asyncio_loop())
    loop.run_forever()


if __name__ == "__main__":
    main()
