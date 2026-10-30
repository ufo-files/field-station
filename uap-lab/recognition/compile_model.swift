import Foundation
import CoreML
let result = try MLModel.compileModel(at: URL(fileURLWithPath:CommandLine.arguments[1]))
try FileManager.default.copyItem(at:result,to:URL(fileURLWithPath:CommandLine.arguments[2]))
print(CommandLine.arguments[2])
