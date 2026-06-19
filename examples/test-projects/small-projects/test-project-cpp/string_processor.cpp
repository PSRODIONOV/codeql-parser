/**
 * StringProcessor - реализация
 */

#include "string_processor.h"
#include <algorithm>
#include <cctype>
#include <cstddef>

StringProcessor::StringProcessor() : processedCount(0) {
}

StringProcessor::~StringProcessor() {
}

std::string StringProcessor::toUpper(const std::string& str) {
    std::string result = str;
    std::transform(result.begin(), result.end(), result.begin(), ::toupper);
    incrementProcessed();
    return result;
}

std::string StringProcessor::toLower(const std::string& str) {
    std::string result = str;
    std::transform(result.begin(), result.end(), result.begin(), ::tolower);
    incrementProcessed();
    return result;
}

std::string StringProcessor::reverse(const std::string& str) {
    std::string result = str;
    std::reverse(result.begin(), result.end());
    incrementProcessed();
    return result;
}

bool StringProcessor::isPalindrome(const std::string& str) {
    std::string reversed = reverse(str);
    return str == reversed;
}

bool StringProcessor::contains(const std::string& str, char c) {
    incrementProcessed();
    return str.find(c) != std::string::npos;
}

int StringProcessor::countChars(const std::string& str, char c) {
    int count = 0;
    for (size_t i = 0; i < str.length(); i++) {
        if (str[i] == c) {
            count++;
        }
    }
    incrementProcessed();
    return count;
}

int StringProcessor::wordCount(const std::string& str) {
    if (str.empty()) {
        return 0;
    }
    int count = 1;
    for (size_t i = 0; i < str.length(); i++) {
        if (str[i] == ' ') {
            count++;
        }
    }
    incrementProcessed();
    return count;
}

void StringProcessor::incrementProcessed() {
    processedCount++;
}
