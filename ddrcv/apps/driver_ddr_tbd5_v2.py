"""Compatibility entry point: both TBD5 launchers use the maintained driver."""

from ddrcv.apps.driver_ddr_tbd5 import cli, main


if __name__ == '__main__':
    cli()
