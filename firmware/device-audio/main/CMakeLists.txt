idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES audio_in vad segmap seg_tx driver
    PRIV_REQUIRES esp_timer
)
