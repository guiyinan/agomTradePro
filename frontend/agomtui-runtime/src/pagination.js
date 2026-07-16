export function clientPage(rows, page = 1, pageSize = 100) {
    const safeRows = Array.isArray(rows) ? rows : [];
    const safeSize = Math.max(1, Number(pageSize) || 100);
    const totalPages = Math.max(1, Math.ceil(safeRows.length / safeSize));
    const safePage = Math.min(totalPages, Math.max(1, Number(page) || 1));
    const start = (safePage - 1) * safeSize;
    return {
        rows: safeRows.slice(start, start + safeSize),
        pager: safeRows.length > safeSize
            ? {
                client_side: true,
                page: safePage,
                total_pages: totalPages,
                total_rows: safeRows.length,
                has_previous: safePage > 1,
                has_next: safePage < totalPages,
            }
            : null,
    };
}
