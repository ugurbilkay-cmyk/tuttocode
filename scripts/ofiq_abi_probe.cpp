// Native layout probe for the pinned official OFIQ C API headers.
#include <cstddef>
#include <iostream>
#include "ofiq_structs_c.h"
int main() {
    std::cout << "{\"Image\":" << sizeof(Image)
              << ",\"BoundingBox\":" << sizeof(BoundingBox)
              << ",\"QualityMeasureResult\":" << sizeof(QualityMeasureResult)
              << ",\"FaceImageQualityAssessment\":" << sizeof(FaceImageQualityAssessment) << "}";
}
