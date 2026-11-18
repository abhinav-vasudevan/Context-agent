import sys

from gradebook import GradeBook
from grading import letter_grade


def main():
    book = GradeBook()
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "quit":
            break
        try:
            if parts[0] == "student":
                book.add_student(parts[1])
            elif parts[0] == "grade":
                book.add_grade(parts[1], parts[2], float(parts[3]))
            elif parts[0] == "report":
                for rank, name in enumerate(book.ranking(), 1):
                    avg = book.average(name)
                    print(f"{rank}. {name} {avg:.1f} {letter_grade(avg)}")
            else:
                raise ValueError(f"unknown command {parts[0]}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    main()
