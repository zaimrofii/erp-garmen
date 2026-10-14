import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { cn } from '@/lib/cn';

/**
 * PageHeader - judul halaman + breadcrumb + slot aksi.
 * Layout mobile-first: menumpuk di layar kecil, sejajar kiri-kanan di `lg`.
 */

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: string;
  subtitle?: string;
  breadcrumb?: BreadcrumbItem[];
  actions?: ReactNode;
  className?: string;
}

export function PageHeader({ title, subtitle, breadcrumb, actions, className }: PageHeaderProps) {
  return (
    <header
      className={cn(
        'flex flex-col gap-2 pb-4 lg:flex-row lg:items-center lg:justify-between',
        className,
      )}
    >
      <div>
        {breadcrumb !== undefined && breadcrumb.length > 0 ? (
          <nav
            aria-label="Breadcrumb"
            className="mb-1 flex flex-wrap items-center gap-1 text-xs text-muted-foreground"
          >
            {breadcrumb.map((crumb) => (
              <span key={crumb.label} className="flex items-center gap-1">
                <ChevronRight className="h-3 w-3" aria-hidden="true" />
                {crumb.href !== undefined ? (
                  <Link to={crumb.href} className="transition-colors hover:text-foreground">
                    {crumb.label}
                  </Link>
                ) : (
                  <span>{crumb.label}</span>
                )}
              </span>
            ))}
          </nav>
        ) : null}

        <h1 className="text-2xl font-bold tracking-tight text-foreground">{title}</h1>
        {subtitle !== undefined ? (
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
        ) : null}
      </div>

      {actions !== undefined ? (
        <div className="flex flex-wrap items-center gap-2">{actions}</div>
      ) : null}
    </header>
  );
}
