"""Restore the frozen source backup into a separate partial-payment clone."""

from prepare_reverse_erp_source_fixture import (
    BENCH, PARTIAL_BACKUP_PREFIX, PARTIAL_DATABASE, PARTIAL_SOURCE,
    PARTIAL_TARGET, main,
)


if __name__ == "__main__":
    main(source=PARTIAL_SOURCE, target=PARTIAL_TARGET,
         database=PARTIAL_DATABASE, backup_prefix=PARTIAL_BACKUP_PREFIX,
         log=BENCH / ".hs-reverse-partial-source-setup.log")
