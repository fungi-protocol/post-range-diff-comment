{ inputs, ... }:
{
  perSystem =
    { config, pkgs, ... }:
    {
      checks.tests =
        pkgs.runCommand "tests"
          {
            nativeBuildInputs = [
              pkgs.bash
              pkgs.git
              pkgs.python3
            ];
            POST_RANGE_DIFF_EXECUTABLE = "${config.packages.default}/bin/post-range-diff-comment";
            src = inputs.self;
          }
          ''
            cd "$src"
            python3 -m unittest discover -s tests -v
            mkdir -p "$out"
          '';
    };
}
