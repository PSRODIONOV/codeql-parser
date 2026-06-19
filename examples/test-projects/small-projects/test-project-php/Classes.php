<?php
/** Иерархия классов — Shape и Animal (аналог classes из других малых проектов). */

class Shape {
    protected string $color;

    public function __construct(string $color = 'white') {
        $this->color = $color;
    }

    public function area(): float {
        return 0.0;
    }

    public function perimeter(): float {
        return 0.0;
    }

    public function describe(): string {
        return "Shape(color={$this->color})";
    }
}

class Circle extends Shape {
    const PI = 3.14159265;
    private float $radius;

    public function __construct(float $radius, string $color = 'white') {
        parent::__construct($color);
        $this->radius = $radius;
    }

    public function area(): float {
        return self::PI * $this->radius * $this->radius;
    }

    public function perimeter(): float {
        return 2 * self::PI * $this->radius;
    }

    public function describe(): string {
        return "Circle(r={$this->radius}, color={$this->color})";
    }
}

class Rectangle extends Shape {
    private float $width;
    private float $height;

    public function __construct(float $width, float $height, string $color = 'white') {
        parent::__construct($color);
        $this->width  = $width;
        $this->height = $height;
    }

    public function area(): float {
        return $this->width * $this->height;
    }

    public function perimeter(): float {
        return 2 * ($this->width + $this->height);
    }

    public function isSquare(): bool {
        return $this->width === $this->height;
    }

    public function describe(): string {
        return "Rectangle({$this->width}x{$this->height}, color={$this->color})";
    }
}

class Animal {
    protected string $name;
    protected string $sound;

    public function __construct(string $name, string $sound) {
        $this->name  = $name;
        $this->sound = $sound;
    }

    public function speak(): string {
        return "{$this->name} says {$this->sound}";
    }

    public function move(): string {
        return "{$this->name} moves";
    }
}

class Dog extends Animal {
    private array $tricks = [];

    public function __construct(string $name) {
        parent::__construct($name, 'Woof');
    }

    public function learnTrick(string $trick): void {
        $this->tricks[] = $trick;
    }

    public function showTricks(): string {
        if (empty($this->tricks)) {
            return "{$this->name} knows no tricks";
        }
        return "{$this->name} knows: " . implode(', ', $this->tricks);
    }
}
