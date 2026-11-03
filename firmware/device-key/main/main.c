#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>
#include "esp_random.h"
#include "nvs.h"
#include "nvs_flash.h"
#include "mbedtls/pk.h"
#include "mbedtls/ecp.h"
#include "mbedtls/sha256.h"
#ifdef ARDUINO
#include <Arduino.h>
#else
#include "driver/usb_serial_jtag.h"
#include "driver/usb_serial_jtag_vfs.h"
#endif

#define DOMAIN "ZHENLU-DEVICE-AUTH-V1:"
#define NONCE_BYTES 32

static mbedtls_pk_context device_key;

static int random_bytes(void *ctx, unsigned char *out, size_t len) {
    (void)ctx;
    esp_fill_random(out, len);
    return 0;
}

static int load_or_create_key(void) {
    nvs_handle_t nvs;
    unsigned char buffer[256];
    size_t length = sizeof(buffer);
    if (nvs_open("identity", NVS_READWRITE, &nvs) != ESP_OK) return -1;
    esp_err_t err = nvs_get_blob(nvs, "private", buffer, &length);
    if (err == ESP_OK) {
        int result = mbedtls_pk_parse_key(&device_key, buffer, length, NULL, 0, random_bytes, NULL);
        memset(buffer, 0, sizeof(buffer));
        nvs_close(nvs);
        return result;
    }
    if (err != ESP_ERR_NVS_NOT_FOUND) { nvs_close(nvs); return -1; }
    int result = mbedtls_pk_setup(&device_key, mbedtls_pk_info_from_type(MBEDTLS_PK_ECKEY));
    if (result == 0) result = mbedtls_ecp_gen_key(MBEDTLS_ECP_DP_SECP256R1, mbedtls_pk_ec(device_key), random_bytes, NULL);
    if (result != 0) { nvs_close(nvs); return result; }
    int size = mbedtls_pk_write_key_der(&device_key, buffer, sizeof(buffer));
    if (size <= 0) { nvs_close(nvs); return -1; }
    err = nvs_set_blob(nvs, "private", buffer + sizeof(buffer) - size, (size_t)size);
    if (err == ESP_OK) err = nvs_commit(nvs);
    memset(buffer, 0, sizeof(buffer));
    nvs_close(nvs);
    return err == ESP_OK ? 0 : -1;
}

static void write_text(const char *value) {
#ifdef ARDUINO
    Serial.print(value);
#else
    fputs(value, stdout);
#endif
}

static void print_hex(const unsigned char *data, size_t size) {
    static const char digits[] = "0123456789abcdef";
    for (size_t i = 0; i < size; ++i) {
        char pair[3] = {digits[data[i] >> 4], digits[data[i] & 15], '\0'};
        write_text(pair);
    }
    write_text("\n");
#ifndef ARDUINO
    fflush(stdout);
#endif
}

static int hex_digit(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int decode_nonce(const char *input, unsigned char *nonce) {
    if (strlen(input) != NONCE_BYTES * 2) return -1;
    for (size_t i = 0; i < NONCE_BYTES; ++i) {
        int high = hex_digit(input[2 * i]), low = hex_digit(input[2 * i + 1]);
        if (high < 0 || low < 0) return -1;
        nonce[i] = (unsigned char)((high << 4) | low);
    }
    return 0;
}

static void process_command(const char *line) {
    if (strcmp(line, "ZL1 PUB") == 0) {
        unsigned char pub[160];
        int size = mbedtls_pk_write_pubkey_der(&device_key, pub, sizeof(pub));
        if (size <= 0) { write_text("ZL1 ERR public\n"); return; }
        write_text("ZL1 PUB ");
        print_hex(pub + sizeof(pub) - size, (size_t)size);
    } else if (strncmp(line, "ZL1 SIGN ", 9) == 0) {
        unsigned char nonce[NONCE_BYTES], hash[32], signature[128];
        unsigned char message[sizeof(DOMAIN) - 1 + NONCE_BYTES];
        size_t sig_len = 0;
        if (decode_nonce(line + 9, nonce) != 0) { write_text("ZL1 ERR nonce\n"); return; }
        memcpy(message, DOMAIN, sizeof(DOMAIN) - 1);
        memcpy(message + sizeof(DOMAIN) - 1, nonce, sizeof(nonce));
        if (mbedtls_sha256(message, sizeof(message), hash, 0) != 0 ||
            mbedtls_pk_sign(&device_key, MBEDTLS_MD_SHA256, hash, sizeof(hash), signature,
                            sizeof(signature), &sig_len, random_bytes, NULL) != 0) {
            write_text("ZL1 ERR signing\n");
            return;
        }
        write_text("ZL1 SIG ");
        print_hex(signature, sig_len);
    } else {
        write_text("ZL1 ERR command\n");
    }
}

static bool initialize_identity(void) {
    mbedtls_pk_init(&device_key);
    // 不自动擦除 NVS；失败时不能悄悄替换设备身份。
    return nvs_flash_init() == ESP_OK && load_or_create_key() == 0;
}

#ifdef ARDUINO
static bool identity_ready = false;
static char line_buffer[160];
static size_t line_size = 0;
static bool line_overflow = false;
void setup(void) {
    Serial.begin(115200);
    identity_ready = initialize_identity();
}
void loop(void) {
    while (Serial.available()) {
        int c = Serial.read();
        if (c == '\n') {
            if (!identity_ready) write_text("ZL1 ERR identity\n");
            else if (line_overflow) write_text("ZL1 ERR length\n");
            else { line_buffer[line_size] = '\0'; process_command(line_buffer); }
            line_size = 0;
            line_overflow = false;
        } else if (c != '\r') {
            if (line_size < sizeof(line_buffer) - 1 && !line_overflow) line_buffer[line_size++] = (char)c;
            else line_overflow = true;
        }
    }
    delay(5);
}
#else
void app_main(void) {
    usb_serial_jtag_driver_config_t config = USB_SERIAL_JTAG_DRIVER_CONFIG_DEFAULT();
    if (usb_serial_jtag_driver_install(&config) != ESP_OK) return;
    usb_serial_jtag_vfs_use_driver();
    setvbuf(stdout, NULL, _IONBF, 0);
    if (!initialize_identity()) { write_text("ZL1 ERR identity\n"); return; }
    char line[160];
    while (fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = '\0';
        process_command(line);
    }
}
#endif
