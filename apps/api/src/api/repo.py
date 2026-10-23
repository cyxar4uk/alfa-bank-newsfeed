"""Чтение данных компаний из БД."""

from typing import Protocol

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from api.contract import ImportedFile, IndustryPosition
from api.okved import okved_prefix
from api.profile import LARGE_REVENUE
from api.records import COMPANY_FIELDS, CompanyRecord, Flow

_COLUMNS = ", ".join(COMPANY_FIELDS)
_CP_COLUMNS = ", ".join(f"c.{name} AS cp_{name}" for name in COMPANY_FIELDS)


class CompanyRepo(Protocol):
    def get_company(self, company_id: str) -> CompanyRecord | None: ...

    def list_companies(self, large: bool, limit: int, offset: int) -> list[CompanyRecord]: ...

    def group(self, group_id: str, exclude: str, limit: int) -> tuple[int, list[str]]: ...

    def flows(self, company_id: str) -> list[Flow]: ...

    def group_records(self, group_id: str, exclude: str) -> list[CompanyRecord]: ...

    def industry(self, company: CompanyRecord) -> IndustryPosition | None: ...

    def imported_files(self) -> list[ImportedFile]: ...


class PgCompanyRepo:
    def __init__(self, pool: ConnectionPool) -> None:
        self.pool = pool

    def get_company(self, company_id: str) -> CompanyRecord | None:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            row = cur.execute(f"SELECT {_COLUMNS} FROM companies WHERE id = %s", (company_id,)).fetchone()
        return CompanyRecord(**row) if row else None

    def list_companies(self, large: bool, limit: int, offset: int) -> list[CompanyRecord]:
        where = "WHERE revenue > %(large)s" if large else ""
        query = f"""
            SELECT {_COLUMNS} FROM companies {where}
            ORDER BY revenue DESC NULLS LAST, id LIMIT %(limit)s OFFSET %(offset)s
        """
        params = {"large": LARGE_REVENUE, "limit": limit, "offset": offset}
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            return [CompanyRecord(**row) for row in cur.execute(query, params).fetchall()]

    def group(self, group_id: str, exclude: str, limit: int) -> tuple[int, list[str]]:
        with self.pool.connection() as conn:
            count = conn.execute("SELECT count(*) FROM companies WHERE group_id = %s", (group_id,))
            size = count.fetchone()[0]
            members = conn.execute(
                """
                SELECT id FROM companies WHERE group_id = %s AND id <> %s
                ORDER BY revenue DESC NULLS LAST, id LIMIT %s
                """,
                (group_id, exclude, limit),
            ).fetchall()
        return size, [m[0] for m in members]

    def group_records(self, group_id: str, exclude: str) -> list[CompanyRecord]:
        """Все другие компании группы — для сигналов группы в карте чувствительности."""
        query = f"""
            SELECT {_COLUMNS} FROM companies WHERE group_id = %s AND id <> %s
            ORDER BY revenue DESC NULLS LAST, id
        """
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            return [CompanyRecord(**row) for row in cur.execute(query, (group_id, exclude)).fetchall()]

    def flows(self, company_id: str) -> list[Flow]:
        query = f"""
            -- самоплатёж попадает только в исходящие, чтобы не считать его дважды
            WITH f AS (
                SELECT beneficiary AS cp, 'out' AS direction, sum(amount) AS amount, sum(payments) AS payments
                FROM payments WHERE payer = %(id)s GROUP BY beneficiary
                UNION ALL
                SELECT payer, 'in', sum(amount), sum(payments)
                FROM payments WHERE beneficiary = %(id)s AND payer <> beneficiary GROUP BY payer
            )
            SELECT f.cp, f.direction, f.amount, f.payments, {_CP_COLUMNS}
            FROM f LEFT JOIN companies c ON c.id = f.cp
        """
        result = []
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            for row in cur.execute(query, {"id": company_id}):
                cp = None
                if row["cp_id"] is not None:
                    cp = CompanyRecord(**{name: row[f"cp_{name}"] for name in COMPANY_FIELDS})
                result.append(
                    Flow(
                        counterparty_id=row["cp"],
                        direction=row["direction"],
                        amount=float(row["amount"]),
                        payments=int(row["payments"]),
                        counterparty=cp,
                    )
                )
        return result

    def industry(self, company: CompanyRecord) -> IndustryPosition | None:
        prefix = okved_prefix(company.okved_code)
        if not company.okved_code or not prefix or not company.revenue:
            return None
        query = """
            SELECT count(*) FILTER (WHERE okved_code = %(code)s),
                   count(*) FILTER (WHERE okved_code = %(code)s AND revenue > %(revenue)s),
                   count(*) FILTER (WHERE okved_code = %(code)s AND revenue < %(revenue)s),
                   count(*),
                   count(*) FILTER (WHERE revenue > %(revenue)s)
            FROM companies
            WHERE okved_class = %(prefix)s AND revenue IS NOT NULL
        """
        params = {"code": company.okved_code, "revenue": company.revenue, "prefix": prefix}
        with self.pool.connection() as conn:
            total, higher, lower, class_total, class_higher = conn.execute(query, params).fetchone()
        if not total:
            return None
        return IndustryPosition(
            okved=company.okved_code,
            rank=higher + 1,
            total=total,
            okved_class=prefix,
            class_rank=class_higher + 1,
            class_total=class_total,
            percentile=round(lower / total, 4),
        )

    def imported_files(self) -> list[ImportedFile]:
        with self.pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            query = "SELECT file, rows_read, rows_loaded, rows_skipped, loaded_at FROM imported_files"
            rows = cur.execute(query + " ORDER BY file").fetchall()
        return [ImportedFile(**row) for row in rows]
