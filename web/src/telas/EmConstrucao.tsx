import { Card, CardContent } from '@/components/ui/card'

export default function EmConstrucao({ item }: { item: string }) {
  return (
    <Card>
      <CardContent className="pt-6 text-sm text-muted-foreground">Esta tela chega no item {item} da fase B.</CardContent>
    </Card>
  )
}
