"""SQL lexer. (Break into tokens) """

from __future__ import annotations
from dataclasses import dataclass
from enum import StrEnum

class TokenType(StrEnum):
    """Token categories understood by the parser."""
    IDENTIFIER = "identifier"
    INTEGER = "integer"
    STRING = "string"
    KEYWORD = "keyword"
    OPERATOR = "operator"
    COMMA = "comma"
    LEFT_PAREN = "left_paren"
    RIGHT_PAREN = "right_paren"
    SEMICOLON = "semicolon"
    STAR = "star"
    EOF = "eof"

KEYWORDS = {
    "BEGIN", "COMMIT", "CREATE", "DELETE",
    "FROM", "INDEX", "INSERT", "INT",
    "INTO", "ON", "ROLLBACK", "SELECT",
    "TABLE", "TEXT", "VALUES", "WHERE",
}

@dataclass(frozen=True, slots=True)
class Token:
    token_type: TokenType
    value: str
    position: int

def tokenize(sql: str) -> list[Token]:
    """Turn SQL text into tokens."""
    tokens: list[Token] = []
    index = 0
    while index < len(sql):
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if char.isalpha() or char == "_":
            start = index
            index += 1
            while index < len(sql) and (sql[index].isalnum() or sql[index] == "_"):
                index += 1
            raw = sql[start:index]
            upper = raw.upper()
            if upper in KEYWORDS:
                tokens.append(Token(TokenType.KEYWORD, upper, start))
            else:
                tokens.append(Token(TokenType.IDENTIFIER, raw, start))
            continue

        if char.isdigit() or (char == "-" and _next_is_digit(sql, index)):
            start = index
            index += 1
            while index < len(sql) and sql[index].isdigit():
                index += 1
            tokens.append(Token(TokenType.INTEGER, sql[start:index], start))
            continue

        if char == "'":
            token, index = _read_string(sql, index)
            tokens.append(token)
            continue

        if char == ",":
            tokens.append(Token(TokenType.COMMA, char, index))
            index += 1
            continue

        if char == "(":
            tokens.append(Token(TokenType.LEFT_PAREN, char, index))
            index += 1
            continue

        if char == ")":
            tokens.append(Token(TokenType.RIGHT_PAREN, char, index))
            index += 1
            continue

        if char == ";":
            tokens.append(Token(TokenType.SEMICOLON, char, index))
            index += 1
            continue

        if char == "*":
            tokens.append(Token(TokenType.STAR, char, index))
            index += 1
            continue

        if char in {"=", "!", "<", ">"}:
            token, index = _read_operator(sql, index)
            tokens.append(token)
            continue

        raise SyntaxError(f"unexpected character {char!r} at position {index}")

    tokens.append(Token(TokenType.EOF, "", len(sql)))
    return tokens

def _next_is_digit(sql: str, index: int) -> bool:
    return index + 1 < len(sql) and sql[index + 1].isdigit()

def _read_string(sql: str, start: int) -> tuple[Token, int]:
    index = start + 1
    chars: list[str] = []
    while index < len(sql):
        char = sql[index]
        if char == "'":
            if index + 1 < len(sql) and sql[index + 1] == "'":
                chars.append("'")
                index += 2
                continue
            return Token(TokenType.STRING, "".join(chars), start), index + 1
        chars.append(char)
        index += 1
    raise SyntaxError(f"unterminated string starting at position {start}")

def _read_operator(sql: str, start: int) -> tuple[Token, int]:
    if sql.startswith("!=", start) or sql.startswith("<=", start) or sql.startswith(">=", start):
        return Token(TokenType.OPERATOR, sql[start : start + 2], start), start + 2
    if sql[start] in {"=", "<", ">"}:
        return Token(TokenType.OPERATOR, sql[start], start), start + 1
    raise SyntaxError(f"unexpected operator at position {start}")