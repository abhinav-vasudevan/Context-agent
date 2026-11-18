### FILE: lexer.py
```python
import re

def tokenize(expr):
    tokens = re.findall(r'\d+\.\d+|\d+|\+|-|\*|\/|\^|\(|\)', expr)
    if not tokens:
        raise ValueError("Empty expression")
    return tokens
```

### FILE: evaluator.py
```python
import operator

def apply_operator(ops, operands):
    op = ops.pop()
    right = operands.pop()
    left = operands.pop()
    if op == '^':
        return left ** right
    elif op in '+-':
        return operator.add(left, right) if op == '+' else operator.sub(left, right)
    elif op in '*/':
        return operator.mul(left, right) if op == '*' else operator.truediv(left, right)

def evaluate(expr):
    tokens = tokenize(expr)
    if tokens[0] == '(':
        tokens = tokens[1:]
        tokens = tokens[:-1]
    if tokens[0] == '-':
        tokens = ['-' if token == '-' else '+' if token == '+' else token for token in tokens]
    ops = []
    operands = []
    for token in tokens:
        if token in '+-*/^':
            while ops and ops[-1] != '(' and (token in '+-') != (ops[-1] in '+-'):
                operands.append(apply_operator(ops, operands))
            ops.append(token)
        elif token == '(':
            ops.append(token)
        elif token == ')':
            while ops[-1] != '(':
                operands.append(apply_operator(ops, operands))
            ops.pop()
        else:
            operands.append(float(token))
    while ops:
        operands.append(apply_operator(ops, operands))
    return round(operands[0], 6)
```

### FILE: main.py
```python
import sys

def print_result(result):
    if result % 1 == 0:
        print(int(result))
    else:
        print(f"{result:.6f}".rstrip('0').rstrip('.'))

if __name__ == "__main__":
    while True:
        expr = input("> ")
        if expr.lower() == 'quit':
            break
        try:
            result = evaluate(expr)
            print_result(result)
        except ZeroDivisionError:
            print("Error: Division by zero")
        except ValueError as e:
            print(f"Error: {str(e)}")
```