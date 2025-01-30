cmake .. ^
  -G "Visual Studio 15 2017" ^
  -DCMAKE_CONFIGURATION_TYPES:STRING="Debug;Release" ^
  -DCMAKE_PROJECT_TOP_LEVEL_INCLUDES:STRING="third_party/cmake/conan_provider.cmake"
