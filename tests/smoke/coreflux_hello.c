#include <linux/init.h>
#include <linux/module.h>

static int __init coreflux_hello_init(void)
{
    pr_info("coreflux phase 0 smoke module loaded\n");
    return 0;
}

static void __exit coreflux_hello_exit(void)
{
    pr_info("coreflux phase 0 smoke module unloaded\n");
}

module_init(coreflux_hello_init);
module_exit(coreflux_hello_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("CoreFlux kernel module smoke test");
