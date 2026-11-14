export default function Panel({
  title,
  description,
  action,
  children,
  className = "",
  bodyClassName = "",
}) {
  return (
    <section
      className={`rounded-xl border border-(--border-color) bg-(--surface) ${className}`}
    >
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 p-5 pb-0">
          <div>
            {title && <h3 className="font-semibold">{title}</h3>}
            {description && (
              <p className="mt-1 text-xs leading-5 text-(--text-secondary)">
                {description}
              </p>
            )}
          </div>
          {action}
        </header>
      )}
      <div className={`p-5 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
