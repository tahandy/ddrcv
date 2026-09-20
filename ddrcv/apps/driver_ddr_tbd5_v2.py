"""Compatibility entry point; use ddrcv.apps.driver_ddr for new integrations."""
from ddrcv.apps.driver_ddr import cli, main


if __name__ == '__main__':
    cli()
