package testproject;

/** Обработчик строк — аналог C++ StringProcessor. */
public class StringProcessor {
    private int processedCount = 0;

    public String toUpper(String str) {
        String result = str.toUpperCase();
        incrementProcessed();
        return result;
    }

    public String toLower(String str) {
        String result = str.toLowerCase();
        incrementProcessed();
        return result;
    }

    public String reverse(String str) {
        String result = new StringBuilder(str).reverse().toString();
        incrementProcessed();
        return result;
    }

    public boolean isPalindrome(String str) {
        String reversed = reverse(str);
        return str.equals(reversed);
    }

    public boolean contains(String str, char c) {
        incrementProcessed();
        return str.indexOf(c) >= 0;
    }

    public int countChars(String str, char c) {
        int count = 0;
        for (int i = 0; i < str.length(); i++) {
            if (str.charAt(i) == c) {
                count++;
            }
        }
        incrementProcessed();
        return count;
    }

    public int wordCount(String str) {
        if (str.isEmpty()) {
            return 0;
        }
        int count = 1;
        for (int i = 0; i < str.length(); i++) {
            if (str.charAt(i) == ' ') {
                count++;
            }
        }
        return count;
    }

    public void incrementProcessed() {
        processedCount++;
    }
}
