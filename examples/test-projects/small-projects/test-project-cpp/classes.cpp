#include "classes.h"
#include <iostream>

int MyClass::static_field_ = 0;

MyClass::MyClass(int val) : field_(val) {
}

MyClass::~MyClass() {
}

void MyClass::do_work() {
    field_++;
    static_field_++;
    std::cout << "Working: " << field_ << std::endl;
}

void MyClass::unused_method() {
    std::cout << "Never called" << std::endl;
}

DataProcessor::DataProcessor() {
    for(int i = 0; i < 10; i++) {
        buffer_[i] = 0;
    }
}

void DataProcessor::process(int data) {
    buffer_[0] = data;
    std::cout << "Processing: " << data << std::endl;
}
