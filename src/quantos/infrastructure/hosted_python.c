/* Isolated CPython with a fixed hash seed before interpreter initialization. */
#include <Python.h>
#include <errno.h>
#include <sys/stat.h>
#include <stdlib.h>
#include <string.h>

#ifndef QUANTOS_PYTHON_HOME
#define QUANTOS_PYTHON_HOME "/install/python"
#endif

#ifndef QUANTOS_PYCACHE_PREFIX
#define QUANTOS_PYCACHE_PREFIX "/tmp/quantos-disabled-bytecode-cache"
#endif

int main(int argc, char **argv) {
    const char *seed = getenv("PYTHONHASHSEED");
    if (seed == NULL || strcmp(seed, "0") != 0) {
        return 78;
    }
    struct stat cache_status;
    if (lstat(QUANTOS_PYCACHE_PREFIX, &cache_status) == 0 || errno != ENOENT) {
        return 78;
    }
    PyConfig config;
    PyStatus status;
    PyConfig_InitIsolatedConfig(&config);
    config.parse_argv = 1;
    config.use_hash_seed = 1;
    config.hash_seed = 0;
    config.write_bytecode = 0;
    config.install_signal_handlers = 1;
    status = PyConfig_SetBytesArgv(&config, argc, argv);
    if (!PyStatus_Exception(status)) {
        status = PyConfig_SetBytesString(&config, &config.home, QUANTOS_PYTHON_HOME);
    }
    if (!PyStatus_Exception(status)) {
        status = PyConfig_SetBytesString(
            &config, &config.pycache_prefix, QUANTOS_PYCACHE_PREFIX);
    }
    if (!PyStatus_Exception(status)) {
        status = Py_InitializeFromConfig(&config);
    }
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        Py_ExitStatusException(status);
    }
    if (PyRun_SimpleString(
            "import sys\n"
            "assert sys.flags.isolated == 1\n"
            "assert sys.flags.ignore_environment == 1\n"
            "assert sys.flags.no_user_site == 1\n"
            "assert sys.flags.safe_path\n"
            "assert sys.flags.hash_randomization == 0\n") != 0) {
        return 78;
    }
    return Py_RunMain();
}
