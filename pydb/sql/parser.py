"""SQL parser."""
from __future__ import annotations
from pydb.sql.ast import (
    BinaryOperator, CreateIndexStatement, CreateTableStatement, DeleteStatement, InsertStatement,
    SelectStatement, Statement, TransactionStatement, WhereClause, )
from pydb.sql.lexer import Token, TokenType, tokenize
from pydb.types import Column, ColumnType, Value

def parse(sql: str) -> Statement:
    """Parse one SQL statement."""
    parser = Parser(tokenize(sql))
    return parser.parse_statement()

class Parser:
    """Recursive-descent parser for PyDB's small SQL subset."""
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.position = 0

    def parse_statement(self) -> Statement:
        token = self._peek()
        if self._matches_keyword("CREATE"):
            statement = self._parse_create()
        elif self._matches_keyword("INSERT"):
            statement = self._parse_insert()
        elif self._matches_keyword("SELECT"):
            statement = self._parse_select()
        elif self._matches_keyword("DELETE"):
            statement = self._parse_delete()
        elif token.value in {"BEGIN", "COMMIT", "ROLLBACK"}:
            statement = self._parse_transaction()
        else:
            raise self._error(f"expected SQL statement, got {token.value!r}")

        self._consume_optional_semicolon()
        self._expect(TokenType.EOF)
        return statement

    def _parse_create(self) -> Statement:
        self._expect_keyword("CREATE")
        if self._matches_keyword("TABLE"):
            return self._parse_create_table()
        if self._matches_keyword("INDEX"):
            return self._parse_create_index()
        raise self._error("expected TABLE or INDEX after CREATE")

    def _parse_create_table(self) -> CreateTableStatement:
        self._expect_keyword("TABLE")
        table_name = self._expect_identifier()
        self._expect(TokenType.LEFT_PAREN)
        columns: list[Column] = []
        while True:
            column_name = self._expect_identifier()
            column_type = self._parse_column_type()
            columns.append(Column(column_name, column_type))
            if not self._match(TokenType.COMMA):
                break
        self._expect(TokenType.RIGHT_PAREN)
        return CreateTableStatement(table_name=table_name, columns=tuple(columns))

    def _parse_create_index(self) -> CreateIndexStatement:
        self._expect_keyword("INDEX")
        index_name = self._expect_identifier()
        self._expect_keyword("ON")
        table_name = self._expect_identifier()
        self._expect(TokenType.LEFT_PAREN)
        column_name = self._expect_identifier()
        self._expect(TokenType.RIGHT_PAREN)
        return CreateIndexStatement( index_name=index_name, table_name=table_name, column_name=column_name, )

    def _parse_insert(self) -> InsertStatement:
        self._expect_keyword("INSERT")
        self._expect_keyword("INTO")
        table_name = self._expect_identifier()
        self._expect_keyword("VALUES")
        self._expect(TokenType.LEFT_PAREN)

        values: list[Value] = []
        if not self._matches(TokenType.RIGHT_PAREN):
            while True:
                values.append(self._parse_value())
                if not self._match(TokenType.COMMA):
                    break
        self._expect(TokenType.RIGHT_PAREN)
        return InsertStatement(table_name=table_name, values=tuple(values))

    def _parse_select(self) -> SelectStatement:
        self._expect_keyword("SELECT")
        self._expect(TokenType.STAR)
        self._expect_keyword("FROM")
        table_name = self._expect_identifier()
        where = self._parse_optional_where()
        return SelectStatement(table_name=table_name, where=where)

    def _parse_delete(self) -> DeleteStatement:
        self._expect_keyword("DELETE")
        self._expect_keyword("FROM")
        table_name = self._expect_identifier()
        where = self._parse_optional_where()
        if where is None:
            raise self._error("DELETE requires a WHERE clause")
        return DeleteStatement(table_name=table_name, where=where)

    def _parse_transaction(self) -> TransactionStatement:
        command = self._peek().value
        self._expect_keyword(command)
        return TransactionStatement(command=command)

    def _parse_optional_where(self) -> WhereClause | None:
        if not self._matches_keyword("WHERE"):
            return None

        self._expect_keyword("WHERE")
        column_name = self._expect_identifier()
        operator = BinaryOperator(self._expect(TokenType.OPERATOR).value)
        value = self._parse_value()
        return WhereClause(column_name=column_name, operator=operator, value=value)

    def _parse_column_type(self) -> ColumnType:
        token = self._peek()
        if token.value == "INT":
            self._advance()
            return ColumnType.INT
        if token.value == "TEXT":
            self._advance()
            return ColumnType.TEXT
        raise self._error("expected column type INT or TEXT")

    def _parse_value(self) -> Value:
        token = self._peek()
        if token.token_type == TokenType.INTEGER:
            self._advance()
            return int(token.value)
        if token.token_type == TokenType.STRING:
            self._advance()
            return token.value
        raise self._error("expected literal value")

    def _consume_optional_semicolon(self) -> None:
        self._match(TokenType.SEMICOLON)

    def _expect_identifier(self) -> str:
        token = self._expect(TokenType.IDENTIFIER)
        return token.value

    def _expect_keyword(self, keyword: str) -> Token:
        token = self._peek()
        if token.token_type == TokenType.KEYWORD and token.value == keyword:
            return self._advance()
        raise self._error(f"expected keyword {keyword}")

    def _expect(self, token_type: TokenType) -> Token:
        token = self._peek()
        if token.token_type == token_type:
            return self._advance()
        raise self._error(f"expected {token_type}, got {token.token_type}")

    def _match(self, token_type: TokenType) -> bool:
        if self._matches(token_type):
            self._advance()
            return True
        return False

    def _matches(self, token_type: TokenType) -> bool:
        return self._peek().token_type == token_type

    def _matches_keyword(self, keyword: str) -> bool:
        token = self._peek()
        return token.token_type == TokenType.KEYWORD and token.value == keyword

    def _peek(self) -> Token:
        return self.tokens[self.position]

    def _advance(self) -> Token:
        token = self._peek()
        self.position += 1
        return token

    def _error(self, message: str) -> SyntaxError:
        token = self._peek()
        return SyntaxError(f"{message} at position {token.position}")