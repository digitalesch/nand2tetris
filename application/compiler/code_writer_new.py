# built-in
import logging
from dataclasses import dataclass, field
import argparse, os
from typing import Dict
import xml.etree.ElementTree as ET
import sys

# symbol table custom code
from symbol_table import SymbolTable, VariableNotFound
from compilation_engine_without_tags import CompilationEngine, flatten_list

@dataclass
class VMCommand():
    type:       str = None
    value:      str = None

@dataclass
class CodeWriter():
    class_name:     str # defines writer for class file passed as parameter
    labels:         Dict = field(default_factory=lambda: {'if':0,'while':0})

    '''
        creates class and subroutine symbol tables
    '''
    def __post_init__(self):
        self.symbol_tables = {
            'class': SymbolTable('class'), 
            'subroutine': SymbolTable('subroutine'), 
            'function':SymbolTable('subroutine')
        }
        self.translate = {
            '>': 'gt',
            '<': 'lt',
            '=': 'eq',
        }

    '''
        finds symbol in subroutine level and if not found, searches class symbol table. If both fail, error is thrown
    '''
    def search_symbol_table(self, symbol_name: str):
        # tries to find the symbol in the subroutine symbol table and if not found, in the class symbol table
        try:
            return self.symbol_tables['subroutine'].scope,self.symbol_tables['subroutine'].find_symbol(symbol_name)
        except ValueError:
            return self.symbol_tables['class'].scope,self.symbol_tables['class'].find_symbol(symbol_name)

    '''
        updates symbol tables
    '''
    def update_symbol_table(self, scope: str, symbol_name:str, symbol_type: str, symbol_kind: str):
        self.symbol_tables[scope].define(symbol_name=symbol_name, symbol_type=symbol_type, symbol_kind=symbol_kind)

    '''
        writes expression symbols in order, so it can be postfixed later
    '''
    def write_expression(self, expression: ET, type: str = None) -> list:
        vm_commands = []
        
        if expression:
            logging.debug(f'Writing expression: {expression}')
            for child in expression:
                if child.tag in ['expression','expressionList','subroutineCall']:
                    logging.debug(f'Recursion {child.tag}')
                    vm_commands.append(self.write_expression(child))
                if child.tag in ['identifier']:
                    if type not in ['assignVariable','assignVariableName']:
                        vm_commands.append(VMCommand('variable',child.text))
                        logging.debug(f"Appending {VMCommand('variable',child.text)}")
                    if type in ['assignVariable','assignVariableName']:
                        vm_commands.append(VMCommand('assignVariable',child.text))
                        logging.debug(f"Appending {VMCommand('assignVariable',child.text)}")
                    if type in ['arrayAssignment']:
                        vm_commands.append(VMCommand('arrayAssignment',child.text))
                        logging.debug(f"Appending {VMCommand('arrayAssignment',child.text)}")
                if child.tag in ['keyword']:
                    vm_commands.append(VMCommand('keyword',child.text))
                    logging.debug(f"Appending {VMCommand('keyword',child.text)}")
                if child.tag in ['integerConstant']:
                    vm_commands.append(VMCommand('constant',child.text))
                    logging.debug(f"Appending {VMCommand('constant',child.text)}")
                if child.tag in ['operation','unaryOperation','stringConstant']:
                    vm_commands.append(VMCommand(child.tag,child.text))
                    logging.debug(f"Appending {VMCommand(child.tag,child.text)}")
                if child.tag in ['subroutineCallName']:
                    subroutine_call_values = [subroutine_call_name.text for subroutine_call_name in child]
                    # gets different value if its a built-in
                    logging.debug(f"Appending {VMCommand('function' if subroutine_call_values[0] not in ['Math','Array','Sys','Output', 'Memory'] else 'systemFunction',''.join(subroutine_call_values))}")
                    vm_commands.append(VMCommand('function' if subroutine_call_values[0] not in ['Math','Array','Sys','Output', 'Memory'] else 'systemFunction',''.join(subroutine_call_values)))
                if child.tag in ['arrayType']:
                    logging.debug('Array type expression')
                    vm_commands.append(VMCommand('arrayType',child.find('identifier').text))
                    logging.debug(f"Appending {VMCommand('arrayType',child.find('identifier').text)}")
                    vm_commands.append(self.write_expression(child.find('expression')))
                if child.tag in ['numberParameters']:
                    vm_commands.append(VMCommand('numberParameters',child.text))
                    logging.debug(f"Appending {VMCommand('numberParameters',child.text)}")
        return vm_commands

    '''
        compares two commands
    '''
    def compare_command(self, input: VMCommand, expectation: VMCommand):
        if any(
            [
                (input.type if command.type else None)==command.type and 
                (input.value if command.value else None)==command.value 
                for command in expectation
            ]
        ):
            return input
        else:
            return False

    def postfix_expression(self, expression: list) -> list:
        postfixed_expression = []
        if isinstance(expression,list):
            if len(expression)==1:
                if isinstance(expression[0],VMCommand):
                    return expression[0]
                else:
                    return self.postfix_expression(expression[0])
            else:
                operation = list(filter(lambda x: isinstance(x,VMCommand),[self.compare_command(term,[VMCommand(type='operation'),VMCommand(type='unaryOperation')]) for term in expression if isinstance(term,VMCommand)]))
                if operation:
                    # get expression index in list
                    expression_index = expression.index(operation[0])
                    # unaryOp
                    if expression_index==0:
                        # postfixes expression
                        postfixed_expression.append(self.postfix_expression(expression[1]))
                        # postfixes operand
                        postfixed_expression.append(operation[0])
                        return postfixed_expression
                    # other expressions
                    else:
                        # gets first expression till operand
                        postfixed_expression.append(self.postfix_expression(expression[0:expression_index]))
                        # gets second expression from operand index + 1 till end of list
                        postfixed_expression.append(self.postfix_expression(expression[expression_index+1:]))
                        # gets operand
                        postfixed_expression.append(expression[expression_index])
                        return postfixed_expression
                array_type = list(filter(lambda x: isinstance(x,VMCommand),[self.compare_command(term,[VMCommand(type='arrayType'),VMCommand(type='arrayAssignment')]) for term in expression if isinstance(term,VMCommand)]))
                if array_type:
                    postfixed_expression.append(self.postfix_expression(expression[1:]))
                    postfixed_expression.append(VMCommand(type=array_type[0].type,value=array_type[0].value))
                    return postfixed_expression
                function = list(filter(lambda x: isinstance(x,VMCommand),[self.compare_command(term,[VMCommand(type='function'),VMCommand(type='systemFunction')]) for term in expression if isinstance(term,VMCommand)]))
                if function:
                    # parameters
                    postfixed_expression.append(self.postfix_expression(expression[2]))
                    # numberParameters
                    postfixed_expression.append(self.postfix_expression(expression[1]))
                    # function
                    postfixed_expression.append(self.postfix_expression(expression[0]))
                    return postfixed_expression
                assignment = list(filter(lambda x: isinstance(x,VMCommand),[self.compare_command(term,[VMCommand(type='assignVariable')]) for term in expression if isinstance(term,VMCommand)]))
                if assignment:
                    postfixed_expression.append(self.postfix_expression(expression[1:]))
                    postfixed_expression.append(VMCommand(type=assignment[0].type,value=assignment[0].value))
                    return postfixed_expression                    
                if all([not function,not array_type, not operation, not assignment]):
                    for param in expression:
                        postfixed_expression.append(self.postfix_expression(param))

                    return postfixed_expression
        else:
            postfixed_expression.append(expression)    

        return postfixed_expression

    '''
        returns compiled expression
    '''
    def treat_compiled_expression(self, statement: ET, tag: str=None):
        logging.debug(f"Treating expression {statement.find(tag)} -> {self.write_expression(statement.find(tag),tag)}")
        if tag is None:
            return self.postfix_expression(self.write_expression(statement))
        else:
            return self.postfix_expression(self.write_expression(statement.find(tag),tag))

    '''
        statement treatment
    '''
    def treat_statement(self, statement: ET):
        expression_vm_commands = []
        if statement.tag == 'whileStatement':
            '''
                label L1
                    compiled (expression)
                    not
                    if-goto L2
                    compiled (statements)
                    goto L1
                label L2                    
            '''
            tmp_label = self.labels['while']
            expression_vm_commands.append(VMCommand(type='label',value=f"WHILE_EXP{tmp_label}"))
            self.labels['while']+=1
            expression_vm_commands += self.treat_compiled_expression(statement,'expression')
            expression_vm_commands.append(VMCommand(type='operation',value='~'))
            expression_vm_commands.append(VMCommand(type='ifgoto',value=f'WHILE_END{tmp_label}'))
            for branch_statements_expression in statement.find('statements'):
                expression_vm_commands += self.treat_statement(branch_statements_expression)
            expression_vm_commands.append(VMCommand(type='goto',value=f'WHILE_EXP{tmp_label}'))
            expression_vm_commands.append(VMCommand(type='label',value=f'WHILE_END{tmp_label}'))
        if statement.tag == 'letStatement':
            expression_vm_commands.append(VMCommand(type='literal',value='// Entered let statement'))
            array_assignment = statement.find('arrayAssignment')
            if array_assignment:
                expression_vm_commands.append(VMCommand(type='literal',value='// Array assignment'))
                logging.debug('entered array assignment')
                arrayVariable = self.treat_compiled_expression(array_assignment,'assignVariableName')#[0]
                print(f'Ar: {arrayVariable}')
                logging.debug(f'assignment {arrayVariable}')
                logging.debug(f"Expression inside arrayAssignment {self.write_expression(array_assignment.find('expression'),'expression')}")
                logging.debug(f"Array expression {self.treat_compiled_expression(array_assignment,'expression')}")
                expression_vm_commands += [
                    # treats left hand expression
                    self.treat_compiled_expression(statement,'expression'),
                    VMCommand(type='arrayAssignment',value=arrayVariable.value),
                    # treats right hand operand
                    self.treat_compiled_expression(array_assignment,'expression'),
                    VMCommand(type='operation',value='+'),
                    VMCommand(type='literal',value='pop pointer 1'),
                    VMCommand(type='literal',value='pop that 0'),
                ]
                logging.debug(f'expression {expression_vm_commands}')                
            else:
                expression_vm_commands.append(self.treat_compiled_expression(statement,'expression'))
                logging.debug(f'Compiled expression: {expression_vm_commands}')
                # assigns to variable
                expression_vm_commands.append(self.treat_compiled_expression(statement.find('assignVariable'),'assignVariableName'))
                
        if statement.tag == 'ifStatement':
            '''
                    compiled (expression)
                    not
                    if-goto L1
                    compiled (statements1)
                    goto L2
                label L1
                    compiled (statements2)
                label L2
            '''
            # compiles condition
            tmp_label = self.labels['if']
            self.labels['if'] += 1
            expression_vm_commands += self.treat_compiled_expression(statement,'expression')
            expression_vm_commands.append(VMCommand(type='ifgoto',value=f"IF_TRUE{tmp_label}"))
            expression_vm_commands.append(VMCommand(type='goto',value=f"IF_FALSE{tmp_label}"))
            expression_vm_commands.append(VMCommand(type='label',value=f"IF_TRUE{tmp_label}"))
            for branch_statements_expression in statement.find('statements_if'):
                expression_vm_commands += self.treat_statement(branch_statements_expression)
            expression_vm_commands.append(VMCommand(type='goto',value=f"IF_END{tmp_label}"))
            expression_vm_commands.append(VMCommand(type='label',value=f"IF_FALSE{tmp_label}"))
            else_statements = statement.find('statements_else')
            if else_statements:
                for branch_statements_expression in statement.find('statements_else'):
                    expression_vm_commands += self.treat_statement(branch_statements_expression)
            expression_vm_commands.append(VMCommand(type='label',value=f"IF_END{tmp_label}"))
        if statement.tag == 'returnStatement':
            expression_vm_commands += self.treat_compiled_expression(statement,'expression')
            # null expression returned
            if len(expression_vm_commands)==0:
                expression_vm_commands.append(VMCommand(type='constant',value='0'))    
            expression_vm_commands.append(VMCommand(type='literal',value='return'))
        if statement.tag == 'doStatement':
            expression_vm_commands.append(VMCommand(type='literal',value='// Entered do statement'))
            expression_vm_commands += self.treat_compiled_expression(statement,'expressionList')
            expression_vm_commands += self.treat_compiled_expression(statement,'subroutineCall')            
            expression_vm_commands.append(VMCommand(type='literal',value=f'pop temp 0'))

        return expression_vm_commands

    '''
        compiles file, to output tokens and syntax
    '''
    def compile_files(self, file_path: str):
        if os.path.isfile(f'{os.path.join(os.getcwd(),file_path)}'):
            CompilationEngine(file_path)        
        else:
            for file in os.listdir(file_path):
                if file.endswith(".jack"):
                    CompilationEngine(os.path.join(file_path,file))

    '''
        code for creating class symbol table from XML structure
    '''
    def create_class_symbol_table(self, syntax_tree: ET):
        for class_var_declaration in syntax_tree.iterfind('classVarDec'):
            tmp = []
            for var_type in class_var_declaration:
                # adds to dict since its type or kind
                if var_type.tag in ['keyword','identifier']:
                    # kind and type variables
                    tmp.append(var_type.text)
                if var_type.tag == 'classVarDecList':
                    # inside classVarDecList is possible identifiers (1 or more) names, like "static int x,y;"
                    for var_name in var_type.iter():
                        #print(tmp,var_name)
                        if var_name.tag == 'identifier':
                            self.update_symbol_table('class',var_name.text,tmp[1],tmp[0])

    '''
        creates subroutine symbol table from XML structure
    '''
    def create_subroutine_symbol_table(self, subroutine_declaration: ET):
        tmp_param = []

        subroutine_type = subroutine_declaration.find('keyword').text
        subroutine_name = subroutine_declaration.find('subroutineName').find('identifier').text
        self.symbol_tables['function'].define(subroutine_name,subroutine_type,'local')
        self.symbol_tables['subroutine'].start_subroutine(self.class_name,subroutine_type)
        
        # creates parameters as a list, since comma separates them, ex: "int a, int b" -> ['int', 'a', 'int', 'b']
        for parameter in subroutine_declaration.find('parameterList'):
            if parameter.tag != 'symbol':
                tmp_param.append(parameter.text)
        # writes parameters to symbol table
        if len(tmp_param):
            # rewrites tmp_param, since its appended as <type> <param_name>, ex: int x
            for key, value in {tmp_param[i*2+1]:tmp_param[i*2] for i in range(int(len(tmp_param)/2))}.items():
                # updates the symbol table, since values are of dict type with values {'<variable_name>': '<variable_type'>} -> {'a': 'int', 'b': 'int'}
                self.symbol_tables['subroutine'].define(symbol_name=key, symbol_type=value, symbol_kind='argument')
                    
        # aggregates all local variables into a list
        all_local_var = []
        for variable_declaration in subroutine_declaration.find('subroutineBody').find('subroutineVarDec'):
            # if local variable, by tab varDec exists, append to all_local_var
            if variable_declaration:
                # temporary list for containing each individual var set, ex: "var int length, teste; var char t;" -> [['var', 'int', 'length', 'teste'], ['var', 'char', 't']]
                tmp_local_var = []
                for local_variable in variable_declaration:
                    if local_variable.tag != 'symbol':
                        tmp_local_var.append(local_variable.text)
                all_local_var.append(tmp_local_var)
        
        # writes parameters to subroutine symbol table
        for local_variable_declaration in all_local_var:
            # two first elements have "var" keyword and type of varialbe, rest of list has variable names
            for local_variable_name in local_variable_declaration[2::]:
                self.symbol_tables['subroutine'].define(symbol_name=local_variable_name, symbol_type=local_variable_declaration[1], symbol_kind='local')

        return (subroutine_name, subroutine_type)

    '''

    '''
    def treat_statements(self, subroutine_declaration: ET) -> list:
        # writes expressions
        vm_commands = []
        
        for statements_declaration in subroutine_declaration.find('subroutineBody').find('statements'):
            vm_commands += self.treat_statement(statements_declaration)

        return vm_commands

    '''
        writes VM Commands based on the postifex
    '''
    def write_vm_commands(self, subroutine_specs: tuple, subroutine_declaration: ET):
        vm_commands = []
        # adds function VM code
        function_local_vars = self.symbol_tables['subroutine'].find_type('local')
        vm_commands.append(VMCommand(type='literal',value=f'function {self.class_name}.{subroutine_specs[0]} {len(function_local_vars)}'))

        # adds constructor specific VM code
        if subroutine_specs[1] == 'constructor':
            fields = [value for key, value in self.symbol_tables['class'].symbol_table.items() if value['kind']=='field']
            vm_commands += [
                VMCommand(type='literal', value=f'push constant {len(fields)}'),
                VMCommand(type='literal', value=f'call Memory.alloc 1'),
                VMCommand(type='literal', value=f'pop pointer 0'),
            ]            
        # adds method specific VM code
        if subroutine_specs[1] == 'method':
            # push argument 0 (this) base value and replace with pointer
            vm_commands += [
                VMCommand(type='literal', value=f'push argument 0'),
                VMCommand(type='literal', value=f'pop pointer 0'),
            ]

        vm_commands += flatten_list(self.treat_statements(subroutine_declaration))
        
        procedural_commands = []
        
        for item in vm_commands:
            if item.type == 'literal':
                procedural_commands.append(item.value)
            if item.type in ['constant']:
                procedural_commands.append(f'push constant {item.value}')
            # gets variable index from symbol table
            if item.type in ['variable','assignVariable','arrayAssignment']:
                found_symbol = self.search_symbol_table(item.value)
                procedural_commands.append(f"{'push' if item.type in ['variable','arrayAssignment','arrayType'] else 'pop'} {found_symbol[1]['kind'] if found_symbol[1]['kind'] != 'field' else 'this'} {found_symbol[1]['index']}")
            if item.type in ['arrayType']:
                logging.debug('entered arrayType')
                found_symbol = self.search_symbol_table(item.value)
                procedural_commands.append('// Entered arrayType')
                procedural_commands.append(f"push {found_symbol[1]['kind'] if found_symbol[1]['kind'] != 'field' else 'this'} {found_symbol[1]['index']}")
                procedural_commands.append("add")
                procedural_commands.append("pop pointer 1")
                procedural_commands.append("push that 0")
            if item.type == 'operation':
                operation_transalate = {
                    '=':'eq',
                    '~':'not',
                    '+':'add',
                    '-':'sub',
                    '*':'call Math.multiply 2',
                    '/':'call Math.divide 2',
                    '>':'gt',
                    '<':'lt',
                    '&':'and',
                    '|':'or',
                }
                procedural_commands.append(f'{operation_transalate[item.value]}')                    

            # compiles this / that
            if item.type == 'keyword':
                if item.value in ['true','false','null']:
                    procedural_commands.append(f"push constant 0")
                    if item.value == 'true':
                        procedural_commands.append(f"not")
                else:
                    procedural_commands.append(f"push pointer {0 if item.value == 'this' else 1}")
            
            if item.type in ['function','systemFunction']:
                procedural_commands.append(f"call {item.value} {number_params.value}")                

            # compiles this / that
            if item.type == 'numberParameters':
                number_params = item                

            if item.type == 'ifgoto':
                procedural_commands.append(f"if-goto {item.value}")
            
            if item.type == 'goto':
                procedural_commands.append(f"goto {item.value}")

            if item.type == 'label':
                procedural_commands.append(f"label {item.value}")

            if item.type == 'unaryOperation':
                operation_transalate = {
                    '~':'not',
                    '-':'neg',
                }
                procedural_commands.append(f'{operation_transalate[item.value]}')

            if item.type == 'stringConstant':
                procedural_commands.append('// adding stringConstant creation')
                procedural_commands.append(f'push constant {len(item.value)}')
                procedural_commands.append('call String.new 1')
                for i in range(len(item.value)):
                    procedural_commands.append(f'push constant {ord(item.value[i])}')
                    procedural_commands.append('call String.appendChar 2')
        
        return procedural_commands
    
def main():
    arguments_list = [
        {'name':'file_path','type':str,'help':'specifies the file / directory to be read'}
    ]
    print(f"{os.path.join(os.getcwd(),sys.argv[1],'vm_commands.log')}")
    logging.basicConfig(filename=f"{os.path.join(os.getcwd(),sys.argv[1],'vm_commands.log')}", filemode='w', level=logging.DEBUG)
    logging.info('Started code!')
    parser = argparse.ArgumentParser()

    # if more arguments are used, specifies each of them
    for arg in arguments_list:
        parser.add_argument(
            arg['name'],type=arg['type'],help=arg['help']
        )
    # creates argparse object to get arguments
    args = parser.parse_args()

    processed_files = []

    if os.path.isfile(f'{os.path.join(os.getcwd(),args.file_path)}'):
        CompilationEngine(args.file_path)
        processed_files.append(os.path.join(os.getcwd(),args.file_path))
    else:
        for file in os.listdir(args.file_path):
            if file.endswith(".jack"):
                CompilationEngine(os.path.join(args.file_path,file))
                processed_files.append(os.path.join(args.file_path,file))

    procedural_commands = []

    for file in processed_files:
        file_path, file_full_name = os.path.split(file)
        file_name, file_extension = file_full_name.split('.')
        xml_tree = ET.parse(f"{os.path.join(os.getcwd(),file_path,file_name+'Syntax.xml')}")
        # update class variable table, by using "classVarDec" and "classVarDecList" tag
        class_name = [tag.text for tag in xml_tree.find('className')][0]
        print(f'Compiling {class_name}!')
        logging.info(f'Compiling {class_name}!')


        cw = CodeWriter(class_name)
        
        cw.create_class_symbol_table(xml_tree)

        # checks for subroutines
        for subroutine_declaration in xml_tree.iterfind('subroutineDec'):
            # check for parameter list, to create entry in subroutine symbol table
            tmp_param = []

            subroutine_type = subroutine_declaration.find('keyword').text
            subroutine_name = subroutine_declaration.find('subroutineName').find('identifier').text
            cw.symbol_tables['function'].define(subroutine_name,subroutine_type,'local')

            cw.symbol_tables['subroutine'].start_subroutine(class_name,subroutine_type)
            
            # creates parameters as a list, since comma separates them, ex: "int a, int b" -> ['int', 'a', 'int', 'b']
            for parameter in subroutine_declaration.find('parameterList'):
                if parameter.tag != 'symbol':
                    tmp_param.append(parameter.text)
            # writes parameters to symbol table
            if len(tmp_param):
                # rewrites tmp_param, since its appended as <type> <param_name>, ex: int x
                for key, value in {tmp_param[i*2+1]:tmp_param[i*2] for i in range(int(len(tmp_param)/2))}.items():
                    # updates the symbol table, since values are of dict type with values {'<variable_name>': '<variable_type'>} -> {'a': 'int', 'b': 'int'}
                    cw.symbol_tables['subroutine'].define(symbol_name=key, symbol_type=value, symbol_kind='argument')
                        
            # aggregates all local variables into a list
            all_local_var = []
            for variable_declaration in subroutine_declaration.find('subroutineBody').find('subroutineVarDec'):
                # if local variable, by tab varDec exists, append to all_local_var
                if variable_declaration:
                    # temporary list for containing each individual var set, ex: "var int length, teste; var char t;" -> [['var', 'int', 'length', 'teste'], ['var', 'char', 't']]
                    tmp_local_var = []
                    for local_variable in variable_declaration:
                        if local_variable.tag != 'symbol':
                            tmp_local_var.append(local_variable.text)
                    all_local_var.append(tmp_local_var)
            
            # writes parameters to subroutine symbol table
            for local_variable_declaration in all_local_var:
                # two first elements have "var" keyword and type of varialbe, rest of list has variable names
                for local_variable_name in local_variable_declaration[2::]:
                    cw.symbol_tables['subroutine'].define(symbol_name=local_variable_name, symbol_type=local_variable_declaration[1], symbol_kind='local')
                    

            vm_commands = []
            
            # adds function VM code
            function_local_vars = cw.symbol_tables['subroutine'].find_type('local')
            vm_commands.append(VMCommand(type='literal',value=f'function {class_name}.{subroutine_name} {len(function_local_vars)}'))

            # adds constructor specific VM code
            if subroutine_type == 'constructor':
                ##print(f'initializing constructor code for class {class_name}!')
                fields = [value for key, value in cw.symbol_tables['class'].symbol_table.items() if value['kind']=='field']
                vm_commands += [
                    VMCommand(type='literal', value=f'push constant {len(fields)}'),
                    VMCommand(type='literal', value=f'call Memory.alloc 1'),
                    VMCommand(type='literal', value=f'pop pointer 0'),
                ]            
            # adds method specific VM code
            if subroutine_type == 'method':
                # push argument 0 (this) base value and replace with pointer
                vm_commands += [
                    VMCommand(type='literal', value=f'push argument 0'),
                    VMCommand(type='literal', value=f'pop pointer 0'),
                ]
            
            logging.debug('Initial VM Commands')            
            
            # writes expressions
            for statements_declaration in subroutine_declaration.find('subroutineBody').find('statements'):                
                vm_commands += cw.treat_statement(statements_declaration)

            logging.debug(f"Final VMCode: {[(cmd.type,cmd.value) for cmd in list(flatten_list(vm_commands))]}")
            
            postfix_commands = list(flatten_list(vm_commands))
            
            for item in postfix_commands:
                if item.type == 'literal':
                    procedural_commands.append(item.value)
                if item.type in ['constant']:
                    procedural_commands.append(f'push constant {item.value}')
                # gets variable index from symbol table
                if item.type in ['variable','assignVariable','arrayAssignment']:
                    found_symbol = cw.search_symbol_table(item.value)
                    procedural_commands.append(f"{'push' if item.type in ['variable','arrayAssignment','arrayType'] else 'pop'} {found_symbol[1]['kind'] if found_symbol[1]['kind'] != 'field' else 'this'} {found_symbol[1]['index']}")
                if item.type in ['arrayType']:
                    logging.debug('entered arrayType')
                    found_symbol = cw.search_symbol_table(item.value)
                    procedural_commands.append('// Entered arrayType')
                    procedural_commands.append(f"push {found_symbol[1]['kind'] if found_symbol[1]['kind'] != 'field' else 'this'} {found_symbol[1]['index']}")
                    procedural_commands.append("add")
                    procedural_commands.append("pop pointer 1")
                    procedural_commands.append("push that 0")
                if item.type == 'operation':
                    operation_transalate = {
                        '=':'eq',
                        '~':'not',
                        '+':'add',
                        '-':'sub',
                        '*':'call Math.multiply 2',
                        '/':'call Math.divide 2',
                        '>':'gt',
                        '<':'lt',
                        '&':'and',
                        '|':'or',
                    }
                    procedural_commands.append(f'{operation_transalate[item.value]}')                    

                # compiles this / that
                if item.type == 'keyword':                    
                    if item.value in ['true','false','null']:
                        procedural_commands.append(f"push constant 0")
                        if item.value == 'true':
                            procedural_commands.append(f"not")
                    else:
                        procedural_commands.append(f"push pointer {0 if item.value == 'this' else 1}")
                
                if item.type in ['function','systemFunction']:
                    procedural_commands.append(f"call {item.value} {number_params.value}")                    

                # compiles this / that
                if item.type == 'numberParameters':
                    number_params = item

                if item.type == 'ifgoto':
                    procedural_commands.append(f"if-goto {item.value}")
                
                if item.type == 'goto':
                    procedural_commands.append(f"goto {item.value}")

                if item.type == 'label':
                    procedural_commands.append(f"label {item.value}")

                if item.type == 'unaryOperation':
                    operation_transalate = {
                        '~':'not',
                        '-':'neg',
                    }
                    procedural_commands.append(f'{operation_transalate[item.value]}')

                if item.type == 'stringConstant':
                    procedural_commands.append('// adding stringConstant creation')
                    procedural_commands.append(f'push constant {len(item.value)}')
                    procedural_commands.append('call String.new 1')
                    for i in range(len(item.value)):
                        procedural_commands.append(f'push constant {ord(item.value[i])}')
                        procedural_commands.append('call String.appendChar 2')
        with open(f"{os.path.join(os.getcwd(),file_path,file_name+'.vm')}",'w') as fp:
            fp.write('\n'.join(procedural_commands)+'\n')

def teste():
    xml_string = '''
        <statements>
            <letStatement>
                <keyword>let</keyword>
                <assignVariable>
                    <assignVariableName>
                        <identifier>a</identifier>
                    </assignVariableName>
                </assignVariable>
                <symbol>=</symbol>
                <expression>
                    <symbol>(</symbol>
                    <expression>
                        <symbol>(</symbol>
                        <expression>
                            <integerConstant>7</integerConstant>
                            <operation>-</operation>
                            <arrayType>
                                <identifier>a</identifier>
                                <symbol>[</symbol>
                                <expression>
                                    <integerConstant>3</integerConstant>
                                </expression>
                                <symbol>]</symbol>
                            </arrayType>
                        </expression>
                        <symbol>)</symbol>
                        <operation>-</operation>
                        <subroutineCall>
                            <subroutineCallName>
                                <identifier>Main</identifier>
                                <symbol>.</symbol>
                                <identifier>duble</identifier>
                            </subroutineCallName>
                            <numberParameters>1</numberParameters>
                        </subroutineCall>
                        <symbol>(</symbol>
                        <expressionList>
                            <expression>
                                <integerConstant>2</integerConstant>
                            </expression>
                        </expressionList>
                        <symbol>)</symbol>
                    </expression>
                    <symbol>)</symbol>
                </expression>
                <symbol>;</symbol>
            </letStatement>
        </statements>
    '''

    '''
    root = ET.fromstring(xml_string)
    cw = CodeWriter('Main')
    cw.symbol_tables['class'].define('a','Array','field')

    logging.basicConfig(filename=f"{os.path.join(os.getcwd(),sys.argv[1],'vm_commands.log')}", filemode='w', level=logging.DEBUG)
    # writes expressions
    vm_commands, t = [],[]
    for statements_declaration in root:
        #print(statements_declaration)
        vm_commands += cw.treat_statement(statements_declaration)
        t += cw.write_expression(statements_declaration)


    logging.debug(f"Final VMCode: {[(cmd.type,cmd.value) for cmd in list(flatten_list(vm_commands))]}")

    for item in vm_commands:
        logging.debug(item)
    '''
    cw = CodeWriter('Main')

    teste = [
        #VMCommand(type='arrayType', value='b'),
        [
            [
                [
                    VMCommand(type='constant', value='7'), 
                    VMCommand(type='operation', value='-'), 
                    VMCommand(type='arrayType', value='a'), 
                    [
                        VMCommand(type='constant', value='3')
                    ]
                ], 
                VMCommand(type='operation', value='-'), 
                [
                    VMCommand(type='function', value='Main.duble'), 
                    VMCommand(type='numberParameters', value='1')
                ],
                [
                    VMCommand(type='constant', value='2')
                ]
            ]
        ], 
        VMCommand(type='operation', value='+'), 
        VMCommand(type='constant', value='1')
    ]

    teste = [
        [
            [
                [
                    VMCommand(type='function', value='Main.duble'), 
                    VMCommand(type='numberParameters', value='1'),
                    [
                        [
                            [
                                [
                                    VMCommand(type='function', value='Main.aaaa'), 
                                    VMCommand(type='numberParameters', value='1'),
                                    [
                                        VMCommand(type='constant', value='5')
                                    ]
                                ]
                            ]
                        ]
                    ],
                ]
            ]
        ]
    ] # ((Main.duble((5))))


    teste  = [[VMCommand(type='systemFunction', value='Array.new'), VMCommand(type='numberParameters', value='1'), [[VMCommand(type='constant', value='10')]]]]
    teste2 = [VMCommand(type='arrayType', value='a'), [VMCommand(type='arrayType', value='a'), [VMCommand(type='constant', value='5')]], VMCommand(type='operation', value='*'), VMCommand(type='arrayType', value='b'), [[[VMCommand(type='constant', value='7'), VMCommand(type='operation', value='-'), VMCommand(type='arrayType', value='a'), [VMCommand(type='constant', value='3')]], VMCommand(type='operation', value='-'), [VMCommand(type='function', value='Main.duble'), VMCommand(type='numberParameters', value='2'), [[VMCommand(type='constant', value='2')], [VMCommand(type='constant', value='5')]]]], VMCommand(type='operation', value='+'), VMCommand(type='constant', value='1')]]
    teste3 = [[VMCommand(type='function', value='Main.duble'), VMCommand(type='numberParameters', value='1'), [[VMCommand(type='constant', value='5')]]], VMCommand(type='operation', value='+'), VMCommand(type='constant', value='1')]
    teste4 = [VMCommand(type='arrayType', value='a'), [VMCommand(type='arrayType', value='a'), [VMCommand(type='constant', value='2')]], VMCommand(type='operation', value='*'), VMCommand(type='arrayType', value='b'), [[[VMCommand(type='constant', value='7'), VMCommand(type='operation', value='-'), VMCommand(type='arrayType', value='a'), [VMCommand(type='constant', value='3')]]]]]
    teste5 = [[VMCommand(type='constant', value='7'), VMCommand(type='operation', value='-'), VMCommand(type='arrayType', value='a'), [VMCommand(type='constant', value='3')]]] # (7-a[3]) -> (7-5) = 2
    teste6 = [VMCommand(type='arrayAssignment', value='a'), [VMCommand(type='constant', value='3')],[VMCommand(type='arrayType', value='b'),[VMCommand(type='constant', value='7'), VMCommand(type='operation', value='-'), VMCommand(type='arrayType', value='a'), [VMCommand(type='constant', value='3')]]]] # (7-a[3]) -> (7-5) = 2
    teste7 = [[VMCommand(type='constant', value='8000'), VMCommand(type='operation', value='+'), VMCommand(type='variable', value='position')], [VMCommand(type='constant', value='1')]]

    #cw = CodeWriter('teste')
    #postfixed_statements = cw.postfix_expression(teste7)
    
    #print(postfixed_statements)
    '''
    cw.symbol_tables['subroutine'].define('a','Point','local')
    cw.symbol_tables['subroutine'].define('b','Point','local')
    cw.symbol_tables['subroutine'].define('c','int','local')

    vm = [
        '// starts main',
        'function Main.main  3',
        '// Creates array a',
        'push constant 5',
        'call Array.new 1',
        'pop local 0',
        '// Creates array b',
        'push constant 2',
        'call Array.new 1',
        'pop local 1',
        '// let c = 9',
        'push constant 9',        
        'pop local 2',
        '// a[2] = 3',
        'push constant 3',
        'push local 0',
        'push constant 2',
        'add',
        'pop pointer 1',
        'pop that 0',
        '// a[3] = 5',
        'push constant 5',
        'push local 0',
        'push constant 3',
        'add',
        'pop pointer 1',
        'pop that 0',
        '// c = 8',
        'push constant 8',
        'push local 1',
        'push constant 2',
        'add',
        'pop pointer 1',
        'pop that 0',
        '// starting function'
    ]
    '''

def main():
    arguments_list = [
        {'name':'file_path','type':str,'help':'specifies the file / directory to be read'}
    ]
    print(f"{os.path.join(os.getcwd(),sys.argv[1],'vm_commands.log')}")
    logging.basicConfig(filename=f"{os.path.join(os.getcwd(),sys.argv[1],'vm_commands.log')}", filemode='w', level=logging.DEBUG)
    logging.info('Started code!')
    parser = argparse.ArgumentParser()

    # if more arguments are used, specifies each of them
    for arg in arguments_list:
        parser.add_argument(
            arg['name'],type=arg['type'],help=arg['help']
        )
    # creates argparse object to get arguments
    args = parser.parse_args()

    processed_files = []

    if os.path.isfile(f'{os.path.join(os.getcwd(),args.file_path)}'):
        CompilationEngine(args.file_path)
        processed_files.append(os.path.join(os.getcwd(),args.file_path))
    else:
        for file in os.listdir(args.file_path):
            if file.endswith(".jack"):
                CompilationEngine(os.path.join(args.file_path,file))
                processed_files.append(os.path.join(args.file_path,file))

    vm_commands = []
    for file in processed_files:
        file_path, file_full_name = os.path.split(file)
        file_name, file_extension = file_full_name.split('.')
        xml_tree = ET.parse(f"{os.path.join(os.getcwd(),file_path,file_name+'Syntax.xml')}")
        # update class variable table, by using "classVarDec" and "classVarDecList" tag
        class_name = [tag.text for tag in xml_tree.find('className')][0]

        cw = CodeWriter(class_name)

        cw.create_class_symbol_table(xml_tree)

        # checks for subroutines
        for subroutine_declaration in xml_tree.iterfind('subroutineDec'):
            subroutine_specs = cw.create_subroutine_symbol_table(subroutine_declaration)
            vm_commands += cw.write_vm_commands(subroutine_specs,subroutine_declaration)
    print(vm_commands)

        # write full file to 
    with open(os.path.join(os.path.os.getcwd(),sys.argv[1],file_name+'.vm'),'w') as fp:
        fp.write('\n'.join(vm_commands))

if __name__ == '__main__':
    main()
    #teste()