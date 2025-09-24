// ============================================================
//  iio_reader.c
//  - Read AD4858 blocks via libiio and write float32 frames to stdout (binary)
//  - Platform: Windows/MSVC and Linux/GCC compatible
//  - ASCII-only comments only
// ============================================================

#include <iio.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <stddef.h>
#include <math.h>

#ifdef _WIN32
  #include <fcntl.h>
  #include <io.h>
#endif

// ============================================================
//  [Struct Definition]
//  Packed header for each data block: [n_samp(uint32), n_ch(uint32)]
// ============================================================
#ifdef _MSC_VER
  #pragma pack(push, 1)
  typedef struct {
      uint32_t n_samp;
      uint32_t n_ch;
  } block_hdr_t;
  #pragma pack(pop)
#else
  typedef struct __attribute__((packed)) {
      uint32_t n_samp;
      uint32_t n_ch;
  } block_hdr_t;
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
//  [Main Function]
//  Usage: iio_reader <ip> <block_samples> <debug_corr> <sampling_freq>
//  - Connects to AD4858 device
//  - Reads data blocks via libiio
//  - Writes binary float32 stream to stdout
// ============================================================
int main(int argc, char **argv) {
    const char *ip = "192.168.1.133";   // Default IP
    int block_samples = 16384;          // Default block size
    const char *dev_name = "ad4858";    // Device name
    int debug_corr = 0;                 // Debug correlation flag
    long long sampling_freq = 0;        // User-specified sampling frequency (Hz)

    // ------------------------------------------------------------
    // [Argument Parsing]
    // argv[1] = target IP
    // argv[2] = block_samples
    // argv[3] = debug_corr
    // argv[4] = sampling_frequency
    // ------------------------------------------------------------
    if (argc > 1 && argv[1] && argv[1][0]) ip = argv[1];
    if (argc > 2) {
        int tmp = atoi(argv[2]);
        if (tmp > 0) block_samples = tmp;
    }
    if (argc > 3) {
        debug_corr = atoi(argv[3]);
    }
    if (argc > 4) {
        sampling_freq = atoll(argv[4]); // atoll = string → long long
    }

#ifdef _WIN32
    // Windows: set stdout to binary mode
    _setmode(_fileno(stdout), _O_BINARY);
#endif

    // ------------------------------------------------------------
    // [Context Connection]
    // Connect to remote IIO device (IP)
    // ------------------------------------------------------------
    struct iio_context *ctx = iio_create_network_context(ip);
    if (!ctx) {
        fprintf(stderr, "ERR: failed to connect to %s\n", ip);
        return 1;
    }

    // ------------------------------------------------------------
    // [Device Find]
    // Locate AD4858 device inside IIO context
    // ------------------------------------------------------------
    struct iio_device *dev = iio_context_find_device(ctx, dev_name);
    if (!dev) {
        fprintf(stderr, "ERR: device '%s' not found\n", dev_name);
        iio_context_destroy(ctx);
        return 2;
    }

    // ------------------------------------------------------------
    // [Sampling Frequency Setup]
    // - If provided by user, attempt to write sampling_frequency
    // - Always read back current hw frequency for confirmation
    // ------------------------------------------------------------
    long long hw_freq = 0;
    if (sampling_freq > 0) {
        fprintf(stderr, "[iio_reader] Attempting to set sampling_frequency to %lld Hz\n", sampling_freq);
        if (iio_device_attr_write_longlong(dev, "sampling_frequency", sampling_freq) < 0) {
            fprintf(stderr, "WARN: Failed to set sampling_frequency. Using device default.\n");
        }
    }
    if (iio_device_attr_read_longlong(dev, "sampling_frequency", &hw_freq) >= 0) {
        fprintf(stderr, "[iio_reader] Current sampling_frequency = %lld Hz\n", hw_freq);
    } else {
        fprintf(stderr, "WARN: Could not read sampling_frequency attribute.\n");
    }

    // ------------------------------------------------------------
    // [Channel Enumeration]
    // Collect all voltage* input channels and read their scale
    // ------------------------------------------------------------
    const int total_ch = iio_device_get_channels_count(dev);
    if (total_ch <= 0) {
        fprintf(stderr, "ERR: no channels on device\n");
        iio_context_destroy(ctx);
        return 3;
    }

    struct iio_channel **in_ch = (struct iio_channel**)calloc((size_t)total_ch, sizeof(*in_ch));
    double *scales = (double*)calloc((size_t)total_ch, sizeof(double));
    if (!in_ch || !scales) {
        fprintf(stderr, "ERR: alloc failed\n");
        free(in_ch); free(scales);
        iio_context_destroy(ctx);
        return 4;
    }

    int n_in = 0;
    for (int i = 0; i < total_ch; i++) {
        struct iio_channel *ch = iio_device_get_channel(dev, i);
        if (!ch || iio_channel_is_output(ch)) continue;
        in_ch[n_in] = ch;
        iio_channel_enable(ch);

        // Read scale factor for channel
        double s = 1.0;
        char buf[64];
        if (read_attr_str(ch, "scale", buf, sizeof(buf))) {
            s = atof(buf);
            // Heuristic unit correction
            if (s > 1e4)         s *= 1e-6;   // assume µV → V
            else if (s > 10.0)   s *= 1e-3;   // assume mV → V
        }
        scales[n_in] = s;
        fprintf(stderr, "[iio_reader] ch%02d scale=%.9g V/LSB\n", n_in, s);
        n_in++;
    }

    if (n_in <= 0) {
        fprintf(stderr, "ERR: no input channels enabled\n");
        free(in_ch); free(scales);
        iio_context_destroy(ctx);
        return 5;
    }

    // ------------------------------------------------------------
    // [Buffer Creation]
    // Create IIO buffer with block_samples
    // ------------------------------------------------------------
    struct iio_buffer *buf = iio_device_create_buffer(dev, (size_t)block_samples, false);
    if (!buf) {
        fprintf(stderr, "ERR: failed to create buffer (block=%d)\n", block_samples);
        free(in_ch); free(scales);
        iio_context_destroy(ctx);
        return 6;
    }

    float *out = (float*)malloc(sizeof(float) * (size_t)block_samples * (size_t)n_in);
    if (!out) {
        fprintf(stderr, "ERR: alloc out buffer\n");
        iio_buffer_destroy(buf);
        free(in_ch); free(scales);
        iio_context_destroy(ctx);
        return 7;
    }

    fprintf(stderr, "[iio_reader] connected=%s, dev=%s, inputs=%d, block=%d\n",
            iio_context_get_name(ctx), dev_name, n_in, block_samples);

    // ------------------------------------------------------------
    // [Block Time Estimation]
    // Calculate block duration (ms) from block_samples and fs
    // ------------------------------------------------------------
    if (sampling_freq > 0) {
        double block_time_ms = 1000.0 * (double)block_samples / (double)sampling_freq;
        fprintf(stderr, "[iio_reader] block=%d samples ≈ %.3f ms @ %lld Hz\n",
                block_samples, block_time_ms, sampling_freq);
    }

    int first_block = 1;

    // ============================================================
    //  [Main Acquisition Loop]
    //  - Refills buffer
    //  - Converts raw samples to float
    //  - Writes header + block data to stdout
    //  - Optionally prints debug correlation
    // ============================================================
    for (;;) {
        if (iio_buffer_refill(buf) < 0) {
            fprintf(stderr, "ERR: buffer refill\n");
            break;
        }

        for (int ci = 0; ci < n_in; ci++) {
            struct iio_channel *ch = in_ch[ci];
            const uint8_t *p = (const uint8_t *)iio_buffer_first(buf, ch);
            ptrdiff_t step = iio_buffer_step(buf);

            for (int s = 0; s < block_samples; s++) {
                int64_t val = 0;
                iio_channel_convert(ch, &val, p);   // Convert raw sample
                out[(size_t)s * (size_t)n_in + ci] = (float)(val * scales[ci]);
                p += step;
            }
        }

        // Write block header + data to stdout
        block_hdr_t hdr;
        hdr.n_samp = (uint32_t)block_samples;
        hdr.n_ch   = (uint32_t)n_in;
        fwrite(&hdr, sizeof(hdr), 1, stdout);
        fwrite(out, sizeof(float), (size_t)block_samples * (size_t)n_in, stdout);
        fflush(stdout);

        // Debug correlation (first block only)
        if (first_block && debug_corr) {
            first_block = 0;
            fprintf(stderr, "[debug] inter-channel correlation:\n");
            for (int i = 0; i < n_in; i++) {
                for (int j = 0; j < n_in; j++) {
                    double sumx=0,sumy=0,sumxx=0,sumyy=0,sumxy=0;
                    for (int s = 0; s < block_samples; s++) {
                        double xi = out[(size_t)s * (size_t)n_in + i];
                        double yj = out[(size_t)s * (size_t)n_in + j];
                        sumx+=xi; sumy+=yj;
                        sumxx+=xi*xi; sumyy+=yj*yj;
                        sumxy+=xi*yj;
                    }
                    double n = (double)block_samples;
                    double num = sumxy - (sumx*sumy)/n;
                    double den = sqrt((sumxx - sumx*sumx/n)*(sumyy - sumy*sumy/n));
                    double corr = (den>1e-12)? num/den : 0.0;
                    fprintf(stderr,"%6.3f ", corr);
                }
                fprintf(stderr,"\n");
            }
        }
    }

    // ------------------------------------------------------------
    // [Cleanup]
    // Free all resources and close context
    // ------------------------------------------------------------
    free(out);
    iio_buffer_destroy(buf);
    free(in_ch);
    free(scales);
    iio_context_destroy(ctx);
    return 0;
}
