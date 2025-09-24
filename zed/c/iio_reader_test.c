// ============================================================
//  iio_reader_test.c
//  - AD4858 simple monitoring tool (test purpose)
//  - Each channel value printed every N-th sample
//  - ASCII-only comments only
// ============================================================

#include <iio.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#ifdef _WIN32
  #include <fcntl.h>
  #include <io.h>
#endif

// ============================================================
//  [Helper Function]
//  read_attr_str: read channel attribute into buffer
//  - Returns 1 on success, 0 on failure
// ============================================================
static int read_attr_str(struct iio_channel *ch, const char *attr, char *dst, size_t dst_len) {
    long n = iio_channel_attr_read(ch, attr, dst, dst_len);
    if (n <= 0) return 0;
    if ((size_t)n >= dst_len) n = (long)dst_len - 1;
    dst[n] = '\0';
    return 1;
}

// ============================================================
//  [Struct Definition]
//  ch_info_t: per-channel information
//  - ch      : pointer to iio_channel
//  - index   : channel index
//  - scale   : scale factor (V/LSB)
//  - offset  : offset correction
//  - id      : channel identifier string
//  - p       : buffer pointer (updated every refill)
// ============================================================
typedef struct {
    struct iio_channel *ch;
    int index;
    double scale;
    long offset;
    const char *id;
    const uint8_t *p;
} ch_info_t;

// ============================================================
//  [Main Function]
//  Usage: iio_reader_test <ip>
//  - Connects to AD4858 device via network context
//  - Enumerates voltage input channels
//  - Prints all channel values every 100000th sample
// ============================================================
int main(int argc, char **argv) {
    const char *ip = "192.168.1.133";    // Default device IP
    int block_samples = 1024;            // Block size (samples per buffer)
    const char *dev_name = "ad4858";     // Device name

    if (argc > 1 && argv[1] && argv[1][0]) ip = argv[1];

    // ------------------------------------------------------------
    // [Context Initialization]
    // Connect to remote IIO device using IP
    // ------------------------------------------------------------
    struct iio_context *ctx = iio_create_network_context(ip);
    if (!ctx) {
        fprintf(stderr, "ERR: failed to connect to %s\n", ip);
        return 1;
    }

    // ------------------------------------------------------------
    // [Device Discovery]
    // Find the target device inside context
    // ------------------------------------------------------------
    struct iio_device *dev = iio_context_find_device(ctx, dev_name);
    if (!dev) {
        fprintf(stderr, "ERR: device '%s' not found\n", dev_name);
        iio_context_destroy(ctx);
        return 2;
    }

    // ------------------------------------------------------------
    // [Channel Enumeration]
    // Collect input channels (voltage*) and read attributes
    // ------------------------------------------------------------
    int total_ch = iio_device_get_channels_count(dev);
    ch_info_t *chs = (ch_info_t*)calloc((size_t)total_ch, sizeof(*chs));
    int n_in = 0;

    for (int i = 0; i < total_ch; i++) {
        struct iio_channel *ch = iio_device_get_channel(dev, i);
        if (!ch) continue;
        if (iio_channel_is_output(ch)) continue;
        if (!iio_channel_is_scan_element(ch)) continue;

        const char *id = iio_channel_get_id(ch);
        if (!id) continue;
        if (strncmp(id, "timestamp", 9) == 0) continue;
        if (strncmp(id, "voltage", 7) != 0) continue;

        chs[n_in].ch = ch;
        chs[n_in].id = id;
        chs[n_in].index = iio_channel_get_index(ch);
        iio_channel_enable(ch);

        // --- Read scale attribute ---
        double s = 1.0;
        char buf[64];
        if (read_attr_str(ch, "scale", buf, sizeof(buf))) {
            s = atof(buf);
        }
        chs[n_in].scale = s;

        // --- Read offset attribute ---
        long off = 0;
        if (read_attr_str(ch, "offset", buf, sizeof(buf))) {
            off = atol(buf);
        }
        chs[n_in].offset = off;

        fprintf(stderr, "[init] %s idx=%d scale=%g V/LSB, offset=%ld\n",
                id, chs[n_in].index, s, off);

        n_in++;
    }

    if (n_in <= 0) {
        fprintf(stderr, "ERR: no usable input channels\n");
        free(chs);
        iio_context_destroy(ctx);
        return 3;
    }

    // ------------------------------------------------------------
    // [Buffer Creation]
    // Create buffer for block_samples
    // ------------------------------------------------------------
    struct iio_buffer *buf = iio_device_create_buffer(dev, (size_t)block_samples, false);
    if (!buf) {
        fprintf(stderr, "ERR: buffer create failed\n");
        free(chs);
        iio_context_destroy(ctx);
        return 4;
    }

    printf("=== Realtime monitoring start (every 100000th sample) ===\n");

    // ============================================================
    //  [Main Acquisition Loop]
    //  - Refill buffer
    //  - Iterate over samples
    //  - Print channel values every 100000th sample
    // ============================================================
    long sample_count = 0;
    for (;;) {
        if (iio_buffer_refill(buf) < 0) {
            fprintf(stderr, "ERR: buffer refill failed\n");
            break;
        }

        // Initialize channel pointers for new buffer
        for (int ci = 0; ci < n_in; ci++) {
            chs[ci].p = (const uint8_t *)iio_buffer_first(buf, chs[ci].ch);
        }
        ptrdiff_t step = iio_buffer_step(buf);

        // Loop over block samples
        for (int s = 0; s < block_samples; s++) {
            if (sample_count % 100000 == 0) {  // Print every 100k samples
                printf("[%ld] ", sample_count);
                for (int ci = 0; ci < n_in; ci++) {
                    int64_t raw = 0;
                    iio_channel_convert(chs[ci].ch, &raw, chs[ci].p);
                    double v = ((double)raw + (double)chs[ci].offset) * chs[ci].scale;
                    printf("%s=%.6f V%s",
                           chs[ci].id,
                           v,
                           (ci == n_in - 1 ? "\n" : " , "));
                }
            }

            // Advance buffer pointers
            for (int ci = 0; ci < n_in; ci++) {
                chs[ci].p += step;
            }

            sample_count++;
        }
        fflush(stdout);
    }

    // ------------------------------------------------------------
    // [Cleanup]
    // Free all allocated resources
    // ------------------------------------------------------------
    iio_buffer_destroy(buf);
    free(chs);
    iio_context_destroy(ctx);
    return 0;
}
