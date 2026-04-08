interface LoadingSpinnerProps {
  className?: string;
  text?: string;
}

export function LoadingSpinner({ className = "", text }: LoadingSpinnerProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent" />
      {text && <span className="text-sm text-muted-foreground">{text}</span>}
    </div>
  );
}
