import { useState, useEffect, useRef } from 'react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { fetchTags } from '@/lib/api'
import type { TagInfo } from '@/types'

interface FilterBarProps {
  type: string
  tag: string
  q: string
  total: number
  onTypeChange: (type: string) => void
  onTagChange: (tag: string) => void
  onSearchChange: (q: string) => void
}

const typeOptions = [
  { value: '', label: 'All' },
  { value: 'text', label: 'Text' },
  { value: 'image', label: 'Image' },
  { value: 'video', label: 'Video' },
  { value: 'audio', label: 'Audio' },
]

export function FilterBar({ type, tag, q, total, onTypeChange, onTagChange, onSearchChange }: FilterBarProps) {
  const [tags, setTags] = useState<TagInfo[]>([])
  const [searchInput, setSearchInput] = useState(q)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(null)

  useEffect(() => {
    fetchTags().then(setTags).catch(() => {})
  }, [])

  useEffect(() => {
    setSearchInput(q)
  }, [q])

  function handleSearchInput(value: string) {
    setSearchInput(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      onSearchChange(value)
    }, 300)
  }

  const hasFilters = type || tag || q

  return (
    <div className="space-y-3">
      {/* Search */}
      <div className="relative">
        <svg
          xmlns="http://www.w3.org/2000/svg"
          className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <Input
          placeholder="Search notes..."
          value={searchInput}
          onChange={e => handleSearchInput(e.target.value)}
          className="pl-10"
        />
      </div>

      {/* Type filter chips */}
      <div className="flex flex-wrap gap-2">
        {typeOptions.map(opt => (
          <Badge
            key={opt.value}
            variant={type === opt.value ? 'default' : 'outline'}
            className="cursor-pointer"
            onClick={() => onTypeChange(opt.value)}
          >
            {opt.label}
          </Badge>
        ))}
      </div>

      {/* Tag select + active filter summary */}
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={tag || '__all__'}
          onValueChange={(v) => onTagChange(!v || v === '__all__' ? '' : v)}
        >
          <SelectTrigger className="w-[180px]">
            <SelectValue placeholder="Filter by tag" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="__all__">All tags</SelectItem>
            {tags.map(t => (
              <SelectItem key={t.tag} value={t.tag}>
                {t.tag} ({t.count})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {hasFilters && (
          <>
            <span className="text-sm text-muted-foreground">{total} results</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                onTypeChange('')
                onTagChange('')
                onSearchChange('')
              }}
            >
              Clear filters
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
