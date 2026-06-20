CXX      ?= g++
CXXFLAGS ?= -std=c++11 -Wall -O0 -g

SRcs := main.cpp if_demo.cpp loop_demo.cpp exception_demo.cpp single_stmt_demo.cpp oneline_demo.cpp advanced_demo.cpp negative_demo.cpp pipeline.cpp
OBJS := $(SRcs:.cpp=.o)
BIN  := branches

all: $(BIN)

$(BIN): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJS)

%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(BIN)

.PHONY: all clean
