// iio_reader_monitor_aligned.c : AD4858 실험 모니터링용 (샘플 기준 정렬 출력)
// 각 샘플마다 모든 채널 값을 묶어서, 1초(100000 샘플)마다 한 줄 출력한다.

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
    const uint8_t *p;   // pointer into buffer
} ch_info_t;

int main(int argc, char **argv) {
    const char *ip = "192.168.1.133";    // 장치 IP
    int block_samples = 1024;            // 블록 크기 (1024 샘플씩 읽음)
    const char *dev_name = "ad4858";

    if (argc > 1 && argv[1] && argv[1][0]) ip = argv[1];

    // Context 생성
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

    // 채널 스캔
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

    // 버퍼 생성
    struct iio_buffer *buf = iio_device_create_buffer(dev, (size_t)block_samples, false);
    if (!buf) {
        fprintf(stderr, "ERR: buffer create failed\n");
        free(chs);
        iio_context_destroy(ctx);
        return 4;
    }

    printf("=== Realtime monitoring start (every 100000th sample) ===\n");

    long sample_count = 0;
    for (;;) {
        if (iio_buffer_refill(buf) < 0) {
            fprintf(stderr, "ERR: buffer refill failed\n");
            break;
        }

        // 채널별 버퍼 포인터 초기화
        for (int ci = 0; ci < n_in; ci++) {
            chs[ci].p = (const uint8_t *)iio_buffer_first(buf, chs[ci].ch);
        }
        ptrdiff_t step = iio_buffer_step(buf);

        // 샘플 기준으로 순서대로 출력
        for (int s = 0; s < block_samples; s++) {
            if (sample_count % 100000 == 0) {  // 1초마다 출력 (100kS/s 기준)
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

            // 포인터 전진
            for (int ci = 0; ci < n_in; ci++) {
                chs[ci].p += step;
            }

            sample_count++;
        }
        fflush(stdout);
    }

    iio_buffer_destroy(buf);
    free(chs);
    iio_context_destroy(ctx);
    return 0;
}
