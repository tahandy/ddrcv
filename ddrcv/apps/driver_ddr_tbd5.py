"""Compatibility entry point; use ddrcv.apps.driver_ddr for new integrations."""
from ddrcv.apps.driver_ddr import (
    cli, create_frame_fetcher, create_publisher, create_runtime,
    default_config, main, merge_config, read_config, validate_config,
)


if __name__ == '__main__':
    cli()
