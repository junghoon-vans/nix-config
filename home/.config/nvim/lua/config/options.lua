-- Options are automatically loaded before lazy.nvim startup
-- Default options that are always set: https://github.com/LazyVim/LazyVim/blob/main/lua/lazyvim/config/options.lua
-- Add any additional options here

-- Go-specific settings
vim.g.go_fmt_autosave = 1
vim.g.go_fmt_command = "goimports"

-- Editor settings
vim.opt.relativenumber = true -- Relative line numbers
vim.opt.tabstop = 4           -- Number of spaces tabs count for
vim.opt.shiftwidth = 4        -- Size of an indent
vim.opt.expandtab = true      -- Use spaces instead of tabs
vim.opt.scrolloff = 8         -- Lines of context
vim.opt.wrap = false          -- Disable line wrap

-- Swap file directory
local swapdir = vim.fn.stdpath('cache') .. '/swap'
vim.fn.mkdir(swapdir, 'p', '0700')
vim.opt.directory = swapdir

-- Go uses tabs by default
vim.api.nvim_create_autocmd("FileType", {
    pattern = "go",
    callback = function()
        vim.opt_local.expandtab = false
        vim.opt_local.tabstop = 4
        vim.opt_local.shiftwidth = 4
    end,
})
