"""Create a fresh PMS clone for the native partially paid invoice trial."""

from prepare_reverse_activation_fixture import BENCH, main


if __name__ == "__main__":
    main(target="hs-pms-smoke-reverse-partial.local",
         database="hs_pms_reverse_partial",
         log=BENCH / ".hs-reverse-partial-target-setup.log")
