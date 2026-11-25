idf_component_register(
    SRCS "seg_tx.c"
    INCLUDE_DIRS "include"
    REQUIRES freertos
    PRIV_REQUIRES heap
)
