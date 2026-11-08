
import csv
import io

from collections.abc import Iterable, Mapping
from typing import Any


def build_csv(
    rows: Iterable[Mapping[str, Any]],
    columns: list[tuple[str, str]],
) -> str:
    """
    Genera un CSV utilizando las columnas indicadas.
    """

    output = io.StringIO(newline="")

    writer = csv.writer(
        output,
        lineterminator="\r\n",
    )

    # Encabezados
    writer.writerow([
        label for _, label in columns
    ])

    # Registros
    for row in rows:
        values = []

        for key, _ in columns:
            value = row.get(key)

            if value is None:
                value = ""

            # Protección contra fórmulas CSV.
            if (
                isinstance(value, str)
                and value.lstrip().startswith(
                    ("=", "+", "-", "@")
                )
            ):
                value = "'" + value

            values.append(value)

        writer.writerow(values)

    return output.getvalue()
