import { type HTMLAttributes } from 'react';

type BadgeVariant = 'default' | 'success' | 'danger' | 'warning' | 'info';

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
}

const variantClasses: Record<BadgeVariant, string> = {
  default: 'bg-ash-bg-secondary text-ash-text-secondary',
  success: 'bg-emerald-500/10 text-ash-success',
  danger: 'bg-red-500/10 text-ash-danger',
  warning: 'bg-amber-500/10 text-ash-warning',
  info: 'bg-ash-primary/10 text-ash-primary',
};

function Badge({ variant = 'default', className = '', children, ...props }: BadgeProps) {
  return (
    <span
      className={`
        inline-flex items-center px-1.5 py-0.5 text-2xs font-medium rounded-md
        ${variantClasses[variant]} ${className}
      `.trim()}
      {...props}
    >
      {children}
    </span>
  );
}

export { Badge };
export type { BadgeProps, BadgeVariant };
