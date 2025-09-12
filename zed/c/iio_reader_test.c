// iio_reader_test.c : AD4858 첫 블록의 각 채널 10개 샘플 텍스트 출력
// 목적: 채널 분리 확인 (timestamp scan element 자동 무시 포함)

#include <iio.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#ifdef _WIN32
  #include <fcntl.h>
  #include <io.h>
#endif

// Helper: read attribute string
static int read_attr_str(struct iio_channel *ch, const char *attr, char *dst, size_t dst_len) {
    long n = iio_channel_attr_read(ch, attr, dst, dst_len);
    if (n <= 0) return 0;
    if ((size_t)n >= dst_len) n = (long)dst_len - 1;
    dst[n] = '\0';
    return 1;
}

typedef struct {
    struct iio_channel *ch;
    int index;
    double scale;
    long offset;
    const char *id;
} ch_info_t;

int main(int argc, char **argv) {
    const char *ip = "192.168.1.133";
    int block_samples = 1024; // 작은 블록만 가져옴
    const char *dev_name = "ad4858";

    if (argc > 1 && argv[1] && argv[1][0]) ip = argv[1];

    struct iio_context *ctx = iio_create_network_context(ip);
    if (!ctx) {
        fprintf(stderr, "ERR: failed to connect to %s\n", ip);
        return 1;
    }

    struct iio_device *dev = iio_context_find_device(ctx, dev_name);
    if (!dev) {
        fprintf(stderr, "ERR: device '%s' not found\n", dev_name);
        iio_context_destroy(ctx);
        return 2;
    }

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
        // timestamp 자동 무시
        if (strncmp(id, "timestamp", 9) == 0) {
            fprintf(stderr, "[skip] %s (timestamp)\n", id);
            continue;
        }
        if (strncmp(id, "voltage", 7) != 0) continue;

        chs[n_in].ch = ch;
        chs[n_in].id = id;
        chs[n_in].index = iio_channel_get_index(ch);
        iio_channel_enable(ch);

        // scale
        double s = 1.0;
        char buf[64];
        if (read_attr_str(ch, "scale", buf, sizeof(buf))) {
            s = atof(buf);
        }
        chs[n_in].scale = s;

        // offset
        long off = 0;
        if (read_attr_str(ch, "offset", buf, sizeof(buf))) {
            off = atol(buf);
        }
        chs[n_in].offset = off;

        n_in++;
    }

    if (n_in <= 0) {
        fprintf(stderr, "ERR: no usable input channels\n");
        free(chs);
        iio_context_destroy(ctx);
        return 3;
    }

    // scan index 기준 정렬
    for (int a = 0; a < n_in - 1; a++) {
        for (int b = a + 1; b < n_in; b++) {
            if (chs[a].index > chs[b].index) {
                ch_info_t tmp = chs[a];
                chs[a] = chs[b];
                chs[b] = tmp;
            }
        }
    }

    for (int ci = 0; ci < n_in; ci++) {
        fprintf(stderr, "[test] %s idx=%d scale=%g V/LSB (%.3f µV/LSB), offset=%ld\n",
            chs[ci].id, chs[ci].index, chs[ci].scale, chs[ci].scale * 1e6, chs[ci].offset);
    }

    struct iio_buffer *buf = iio_device_create_buffer(dev, (size_t)block_samples, false);
    if (!buf) {
        fprintf(stderr, "ERR: buffer create failed\n");
        free(chs);
        iio_context_destroy(ctx);
        return 4;
    }

    if (iio_buffer_refill(buf) < 0) {
        fprintf(stderr, "ERR: buffer refill failed\n");
        iio_buffer_destroy(buf);
        free(chs);
        iio_context_destroy(ctx);
        return 5;
    }

    printf("=== First 10 samples per channel (µV) ===\n");
    for (int ci = 0; ci < n_in; ci++) {
        struct iio_channel *ch = chs[ci].ch;
        const uint8_t *p = (const uint8_t *)iio_buffer_first(buf, ch);
        ptrdiff_t step = iio_buffer_step(buf);

        printf("Channel %s (idx=%d):\n", chs[ci].id, chs[ci].index);
        for (int s = 0; s < 10; s++) {
            int64_t raw = 0;
            iio_channel_convert(ch, &raw, p);
            double v = ((double)raw + (double)chs[ci].offset) * chs[ci].scale;
            printf("  sample[%d] = %.3f µV\n", s, v * 1e6);
            p += step;
        }
    }

    iio_buffer_destroy(buf);
    free(chs);
    iio_context_destroy(ctx);
    return 0;
}
