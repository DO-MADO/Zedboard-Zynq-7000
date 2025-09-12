#include <iio.h>   // libiio functions (device connection, data read/write)
#include <stdio.h> // standard I/O functions (printf, getchar)

// Entry point
int main() {
    // Create context over network
    struct iio_context *ctx = iio_create_network_context("192.168.1.133");

    if (!ctx) {  // if connection failed
        printf("Failed to connect to IIO device.\n");
        return 1; // exit with error code
    }

    printf("Connected to: %s\n", iio_context_get_name(ctx));

    printf("Press Enter to exit...\n");
    getchar(); // wait for user input

    iio_context_destroy(ctx); // cleanup
    return 0; // success
}
