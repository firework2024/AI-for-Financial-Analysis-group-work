import { type ButtonHTMLAttributes, forwardRef } from 'react';

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';
type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: 'bg-ash-primary text-white hover:bg-ash-primary/90 focus-visible:ring-ash-primary/50',
  secondary: 'border border-ash-border bg-ash-card text-ash-text hover:bg-ash-hover focus-visible:ring-ash-primary/30',
  ghost: 'text-ash-text-secondary hover:bg-ash-hover hover:text-ash-text focus-visible:ring-ash-primary/30',
  danger: 'bg-ash-danger text-white hover:opacity-90 focus-visible:ring-ash-danger/50',
};

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs rounded-lg',
  md: 'px-3.5 py-1.5 text-sm rounded-lg',
  lg: 'px-5 py-2.5 text-sm rounded-lg',
};

const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'secondary', size = 'md', className = '', disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled}
      className={`
        inline-flex items-center justify-center gap-1.5 font-medium
        transition-colors duration-150
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1
        disabled:opacity-50 disabled:pointer-events-none
        ${variantClasses[variant]} ${sizeClasses[size]} ${className}
      `.trim()}
      {...props}
    >
      {children}
    </button>
  )
);
Button.displayName = 'Button';

export { Button };
export type { ButtonProps, ButtonVariant, ButtonSize };
