#pragma once

class MyClass {
public:
    MyClass(int val);
    ~MyClass();
    void do_work();
    void unused_method();  // Не вызывается
private:
    int field_;
    static int static_field_;
};

class DataProcessor {
public:
    DataProcessor();
    void process(int data);
private:
    int buffer_[10];
};
