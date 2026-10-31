import 'package:cortex_app/theme.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  tearDown(() => Cx.high = false);

  test('extra contrast brightens secondary text and outlines', () {
    final normal = (Cx.faintC, Cx.mutedC, Cx.outlineC, Cx.lineC);
    Cx.high = true;
    double lum(c) => (c as dynamic).computeLuminance() as double;
    expect(lum(Cx.faintC), greaterThan(lum(normal.$1)));
    expect(lum(Cx.mutedC), greaterThan(lum(normal.$2)));
    expect(lum(Cx.outlineC), greaterThan(lum(normal.$3)));
    expect(lum(Cx.lineC), greaterThan(lum(normal.$4)));
    expect(Cx.small.color, Cx.faintC);
  });
}
