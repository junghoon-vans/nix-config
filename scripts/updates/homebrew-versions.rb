require "json"
require "formula"
require "cask/cask_loader"

# Load the pinned files, not the installed tap or Homebrew's current API data.
versions = JSON.parse($stdin.read).to_h do |name, entry|
  path = Pathname(entry.fetch("path"))
  version = if entry.fetch("tap") == "homebrew-cask"
    Cask::CaskLoader.load(path).version.to_s
  else
    Formulary.factory(path).pkg_version.to_s
  end
  [name, version]
end
puts JSON.generate(versions)
