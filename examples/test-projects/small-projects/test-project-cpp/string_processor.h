/**
 * StringProcessor - дополнительный класс
 * Обработка строк
 */

#ifndef STRING_PROCESSOR_H
#define STRING_PROCESSOR_H

#include <string>
#include <vector>

class StringProcessor {
public:
    StringProcessor();
    ~StringProcessor();
    
    // Преобразования
    std::string toUpper(const std::string& str);
    std::string toLower(const std::string& str);
    std::string reverse(const std::string& str);
    
    // Проверки
    bool isPalindrome(const std::string& str);
    bool contains(const std::string& str, char c);
    
    // Статистика
    int countChars(const std::string& str, char c);
    int wordCount(const std::string& str);
    
private:
    int processedCount;
    void incrementProcessed();
};

#endif // STRING_PROCESSOR_H
