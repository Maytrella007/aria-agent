"""
Data Analysis Skill - Analyze data with calculator, code, and database.

Handles math calculations, data queries, statistical analysis,
and generates Python code for complex analysis tasks.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class DataAnalysisSkill(SkillBase):
    name = "data_analysis"
    description = "Analyze data: calculations, statistics, queries, charts"
    requires_tools = []

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        # Detect analysis type
        op = self._detect_analysis(query)

        if op == "calc":
            return self._calculate(query, ctx)
        elif op == "query":
            return self._query_database(query, ctx)
        elif op == "stats":
            return self._statistics(query, ctx)
        else:
            return self._smart_analysis(query, ctx)

    def _detect_analysis(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["query", "consulta", "database", "base de datos", "sql", "select"]):
            return "query"
        if any(w in q for w in ["statistics", "estadística", "average", "promedio", "mean", "median", "std"]):
            return "stats"
        # Check if it's a simple math expression
        if re.search(r'\d+\s*[+\-*/^%]\s*\d+', q) or any(w in q for w in [
            "calculate", "calcular", "how much", "cuánto", "percentage", "porcentaje",
            "convert", "convertir",
        ]):
            return "calc"
        return "smart"

    def _calculate(self, query: str, ctx: SkillContext) -> SkillResult:
        """Perform calculation using calculator tool."""
        # Try to extract a math expression
        expr = self._extract_expression(query)

        if expr:
            result = ctx.tools.execute(Tools.CALCULATOR, expression=expr)
            if result.success:
                return SkillResult(
                    success=True,
                    output=f"{expr} = {result.output}",
                    data={"expression": expr, "result": result.output, "type": "calculation"},
                )

        # Use LLM to translate natural language to math
        if ctx.llm:
            prompt = f"""Convert this request to a mathematical expression:

Request: {query}

Respond with ONLY the mathematical expression (e.g., "15 * 2340 / 100" or "sqrt(144)").
Available functions: sqrt, sin, cos, tan, log, log10, abs, round, pow, pi, e"""

            try:
                response = ctx.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=50,
                )
                if response and response.content:
                    expr = response.content.strip()
                    result = ctx.tools.execute(Tools.CALCULATOR, expression=expr)
                    if result.success:
                        return SkillResult(
                            success=True,
                            output=f"{expr} = {result.output}",
                            data={"expression": expr, "result": result.output, "type": "calculation"},
                        )
            except Exception:
                pass

        return SkillResult(success=False, error="Could not parse calculation")

    def _extract_expression(self, query: str) -> str:
        """Extract mathematical expression from text."""
        # Direct math expression
        m = re.search(r'([\d.]+\s*[+\-*/^%]\s*[\d.]+(?:\s*[+\-*/^%]\s*[\d.]+)*)', query)
        if m:
            return m.group(1)

        # Percentage calculation: "X% of Y"
        m = re.search(r'([\d.]+)\s*%\s*(?:of|de)\s*([\d.]+)', query, re.IGNORECASE)
        if m:
            return f"{m.group(1)} * {m.group(2)} / 100"

        # Function call: "sqrt of X"
        m = re.search(r'(sqrt|sin|cos|tan|log)\s*(?:of|de)?\s*([\d.]+)', query, re.IGNORECASE)
        if m:
            return f"{m.group(1).lower()}({m.group(2)})"

        return ""

    def _query_database(self, query: str, ctx: SkillContext) -> SkillResult:
        """Execute a database query."""
        # Check for direct SQL
        sql_match = re.search(r'(SELECT\s+.+)', query, re.IGNORECASE | re.DOTALL)
        if sql_match:
            sql = sql_match.group(1).strip().rstrip(';') + ';'
            result = ctx.tools.execute(Tools.DATABASE, action="query", sql=sql)
            if result.success:
                return SkillResult(
                    success=True,
                    output=result.output,
                    data={"type": "query", "sql": sql},
                )
            return SkillResult(success=False, error=f"Query failed: {result.error}")

        # Use LLM to generate SQL from natural language
        if ctx.llm:
            # First get table info
            tables = ctx.tools.execute(Tools.DATABASE, action="tables")
            tables_info = tables.output if tables.success else "No tables found"

            prompt = f"""Convert this data request to SQL:

Request: {query}

Available tables:
{tables_info[:1000]}

Respond with ONLY the SQL query (SELECT only)."""

            try:
                response = ctx.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=200,
                )
                if response and response.content:
                    sql = response.content.strip().strip('`').strip()
                    if sql.upper().startswith("SELECT"):
                        result = ctx.tools.execute(Tools.DATABASE, action="query", sql=sql)
                        if result.success:
                            return SkillResult(
                                success=True,
                                output=f"Query: {sql}\n\n{result.output}",
                                data={"type": "query", "sql": sql},
                            )
            except Exception:
                pass

        return SkillResult(success=False, error="Could not execute database query")

    def _statistics(self, query: str, ctx: SkillContext) -> SkillResult:
        """Perform statistical analysis using code execution."""
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for statistical analysis")

        # Extract numbers from query
        numbers = re.findall(r'[\d.]+', query)

        prompt = f"""Write Python code to perform the statistical analysis requested:

Request: {query}
{f'Numbers found: {numbers}' if numbers else ''}

Use only standard library (statistics module).
Print the results clearly. Keep it concise."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            if response and response.content:
                # Extract code from response
                code = response.content
                code_match = re.search(r'```python\n(.+?)```', code, re.DOTALL)
                if code_match:
                    code = code_match.group(1)

                result = ctx.tools.execute(Tools.CODE_EXEC, code=code)
                if result.success:
                    return SkillResult(
                        success=True,
                        output=result.output,
                        data={"type": "statistics", "code": code},
                    )
        except Exception as e:
            return SkillResult(success=False, error=f"Statistics failed: {e}")

        return SkillResult(success=False, error="Could not perform statistical analysis")

    def _smart_analysis(self, query: str, ctx: SkillContext) -> SkillResult:
        """Use LLM + code_exec for complex analysis."""
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for data analysis")

        prompt = f"""Write Python code to answer this data question:

Question: {query}

Requirements:
- Use only standard library modules
- Print clear results
- Keep it under 20 lines"""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            if response and response.content:
                code = response.content
                code_match = re.search(r'```python\n(.+?)```', code, re.DOTALL)
                if code_match:
                    code = code_match.group(1)

                result = ctx.tools.execute(Tools.CODE_EXEC, code=code)
                if result.success:
                    return SkillResult(
                        success=True,
                        output=result.output,
                        data={"type": "analysis", "code": code},
                    )
                return SkillResult(success=False, error=f"Code execution failed: {result.error}")
        except Exception as e:
            return SkillResult(success=False, error=f"Analysis failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")
