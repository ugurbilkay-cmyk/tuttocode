# Mac OFIQ 1.2.0 omits the C API target present in its Linux and Windows files.
# Append this block to OFIQlib/CMakeLists.macos.cmake after the official build.
# It compiles the unchanged upstream wrapper; no quality algorithms are changed.
add_library(ofiq_c SHARED ${PUBLIC_HEADER_LIST_C_API} ${libImplementationSources_clib})
target_link_libraries(ofiq_c PRIVATE ofiq_lib ${OFIQ_LINK_LIB_LIST})
set_target_properties(ofiq_c PROPERTIES PUBLIC_HEADER "${PUBLIC_HEADER_LIST_C_API}")
install(TARGETS ofiq_c CONFIGURATIONS Release DESTINATION Release/lib PUBLIC_HEADER DESTINATION include/)
