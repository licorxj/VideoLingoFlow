import * as React from "react"
import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium ring-offset-background transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 active:scale-[0.98] [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 hover:shadow-md",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground hover:border-primary/40",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
        // 语义色：success / warning / info / ai
        success: "bg-success text-success-foreground shadow-sm hover:bg-success/90",
        warning: "bg-warning text-warning-foreground shadow-sm hover:bg-warning/90",
        info: "bg-info text-info-foreground shadow-sm hover:bg-info/90",
        ai: "bg-ai text-ai-foreground shadow-sm hover:bg-ai/90",
        // 语义色 soft 版（描边 + 浅色背景）
        "success-soft": "bg-success/12 text-success border border-success/30 hover:bg-success/20",
        "warning-soft": "bg-warning/12 text-warning border border-warning/30 hover:bg-warning/20",
        "info-soft": "bg-info/12 text-info border border-info/30 hover:bg-info/20",
        "ai-soft": "bg-ai/12 text-ai border border-ai/30 hover:bg-ai/20",
        "danger-soft": "bg-destructive/12 text-destructive border border-destructive/30 hover:bg-destructive/20",
      },
      size: {
        default: "h-10 px-4 py-2 gap-1.5",
        sm: "h-9 rounded-md px-3 gap-1.5",
        lg: "h-11 rounded-md px-6 gap-2",
        xs: "h-8 rounded-md px-2.5 gap-1 text-xs",
        icon: "h-10 w-10",
        "icon-sm": "h-8 w-8",
        "icon-xs": "h-7 w-7 [&_svg]:size-3.5",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
)

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button"
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />
  }
)
Button.displayName = "Button"

export { Button, buttonVariants }
