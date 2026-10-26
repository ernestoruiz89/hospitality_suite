"""Create a fresh PMS target clone for the native ERPNext invoice cutover."""

from prepare_reverse_activation_fixture import BENCH, main


if __name__ == "__main__":
    main(target="hs-pms-smoke-real-reverse.local",
         database="hs_pms_real_reverse",
         log=BENCH / ".hs-real-reverse-target-setup.log")
