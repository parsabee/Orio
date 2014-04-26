#
# This Orio 
#

import ann_parser, orio.module.module
import sys, re, os, glob
from orio.main.util.globals import *

#-----------------------------------------

class CHiLL(orio.module.module.Module):
    '''Orio's interface to the CHiLL source transformation infrastructure. '''

    def __init__(self, perf_params, module_body_code, annot_body_code, line_no, indent_size, language='C'):
        '''To instantiate the CHiLL rewriting module.'''

        orio.module.module.Module.__init__(self, perf_params, module_body_code, annot_body_code,
                                      line_no, indent_size, language)

    #---------------------------------------------------------------------
    
    def transform(self):
        '''To simply rewrite the annotated code'''

        # to create a comment containing information about the class attributes
        comment = '''
        /*
         perf_params = %s
         module_body_code = "%s"
         annot_body_code = "%s"
         line_no = %s
         indent_size = %s
        */
        ''' % (self.perf_params, self.module_body_code, self.annot_body_code, self.line_no, self.indent_size)


        # CHiLL annotations are of the form:
        # /*@ begin Chill ( transform Recipe(recipe filename) ) @*/
        # ...
        # The code to be transformed by CHiLL here
        # ... 
        # /*@ end Chill @*/
	code = self.annot_body_code
	fname = '_orio_chill_.c'
	hname = '_orio_chill_.h'
	func = getFunction()
	func1 = func.replace("{",";")
	func2 = func1.replace("double *","")
	func2 = func2.split(' ',1)[1]
	funcName = getFuncName()
	
	    

	#print "Informatio variables: \nperf_params: ",self.perf_params,"\nmodule_body_code: ",self.module_body_code,"\nline_no: ",self.line_no,"\nindent_size: ",self.indent_size


	transCMD = re.split(r'[\n\t]+',self.module_body_code)
	print transCMD,len(transCMD)
	tInfo = re.split(r'[ ()\t]+',transCMD[0])
	print tInfo
	del tInfo[-1]

	cmd = ''
	scriptCMD = ""
	CU = 1
	recipeFound = False
	cname = ''
	if tInfo[1] == 'Recipe':
		if len(transCMD) > 1:
			err('orio.module.chill.chill: Recipe file can\'t be added when other transformations are included')
		elif len(tInfo) == 3:
			cname = tInfo[2] 
			cname1, ctype = os.path.splitext(cname)
			recipeFound = True
			if ctype != '.lua':
				err('orio.module.chill.chill: Wrong file type')
		
		elif len(tInfo) < 3:
			err('orio.module.chill.chill: No recipe filename give')
	defines = ''
	cleanScript = False

	cleanArgv = []
	if recipeFound == False:
		scriptCMD=''
		for trans in range(len(transCMD)):
	
			recipeTest = re.split(r'[ ()\t]+',transCMD[trans])
			cleaning = transCMD[trans].replace("\t","")
			cleaning = cleaning.replace("\n","")
			clean2 = cleaning.split(' ')
			if recipeTest[1] == 'Recipe':
				err('orio.module.chill.chill: Recipe file can\'t be added when other transformations are included')

			elif recipeTest[0] == '#define':
				defines = defines + transCMD[trans] + '\n'

			elif clean2[0] == 'run' and clean2[1] == 'clean':
				cleanScript = True
				for c in range(2,len(clean2)):
					cleanArgv.append(clean2[c])

			else:
				tInfo = re.split('({|}|\(|\))',transCMD[trans])
	
				for pos in range(len(tInfo)):
					for key,value in self.perf_params.iteritems():
						if tInfo[pos] == key:
							tInfo[pos] = value
					
				for d in tInfo:
					scriptCMD = scriptCMD + str(d)

				scriptCMD = scriptCMD + '\n'


		tag = ''
		for key,value in self.perf_params.iteritems():
			tag = tag + "_"+str(value)
	

		cname = 'recipe'+tag+'.lua'
	
		try:
		    cfile = open(cname,'w')
		    cfile.write("init(\""+fname.replace("'","") + "\",\""+funcName.replace("'","")+"\",0)\n")   
		    cfile.write("dofile(\"cudaize.lua\")\n\n")
		    cfile.write(scriptCMD)
		    cfile.write("\n")
		    cfile.close()

		except:
		    err('orio.module.chill.chill: cannot open file for writing: %s' % cname)
		##copy the recipes to another file to avoid a mess up in file
		if not os.path.exists('recipes'):
    			os.makedirs('recipes')
	
		cmd = 'cp '+cname+' recipes/./'
		try:
		    os.system(cmd)
		except:
	            err('orio.module.chill.chill:  failed to run command: %s' % cmd)

	if not os.path.isfile(fname):
		try:
		    f = open(fname,'w')
		    f.write(defines)   ##added for debug Axel Y. Rivera (UofU)
		    				    ##This need to be removed
		    f.write(func)
		    f.write(code)
		    f.write("\n}\n\n")
		    f.close()

		except:
		    err('orio.module.chill.chill: cannot open file for writing: %s' % fname)

	if not os.path.isfile(hname):
		try:
		    h = open(hname,'w')    
		    h.write(func1)
		    h.write("\n\n")
		    h.close()

		except:
		    err('orio.module.chill.chill: cannot open file for writing: %s' % hname)

	

	#RUN CUDA-CHILL MUTE FOR DEBUG PURPOUSE
	try:

	    os.path.isfile(cname)

	except:
	    err('orio.module.chill.chill: cannot open file recipe for CUDA-CHiLL: %s' % cname)


	cmd = 'cuda-chill %s' % (cname)
	info('orio.module.chill.chill: running CUDA-CHiLL with command: %s' % cmd)

	try:
	    os.system(cmd)
	except:
            err('orio.module.chill.chill:  failed to run command: %s' % cmd)


##Lazy cleaning
	if cleanScript == True:
		cmd = 'python clean-script.py'
		for c in cleanArgv:
			cmd = cmd + ' ' + c
		info('orio.module.chill.chill: running CUDA-CHiLL with command: %s' % cmd)

		try:
		    os.system(cmd)
		except:
        	    err('orio.module.chill.chill:  failed to run command: %s' % cmd)

## Lazy hammering to take the code and call it from outside
## We compile with nvcc the library and the with g++ we link

	modfile = open('rose__orio_chill_.cu')
	text = modfile.read()
	modfile.close()

	modfile = open('rose__orio_chill_bk.cu','w')
	modfile.write('#include \"_orio_chill_.h\"\n\n')
	modfile.write(text)
	modfile.close()

	cmd = 'cp rose__orio_chill_bk.cu rose__orio_chill_.cu'
	try:
		os.system(cmd)
	except:
	     err('orio.module.chill.chill:  failed to run command: %s' % cmd)

	cmd = 'rm rose__orio_chill_bk.cu'

	try:
		os.system(cmd)
	except:
	     err('orio.module.chill.chill:  failed to run command: %s' % cmd)


	cmd = 'nvcc rose__orio_chill_.cu -c -o rose__orio_chill_.o'
	
	try:
		os.system(cmd)
	except:
		err('orio.module.chill.chill:  failed to compile with nvcc: %s' % cmd)


	fname2 = ''
	if recipeFound == False:
		fname1, ctype = os.path.splitext(fname)
		fname2 = 'rose_' + fname1 + tag + ctype + 'u'
	else:
		fname2 = fname+'u'

	info('orio.module.chill.chill: Output located in: rose_%s' % fname2)

	if recipeFound == False: 
		if not os.path.exists('outputs'):
			os.makedirs('outputs')
	
		cmd = 'cp rose_'+fname+'u outputs/' + fname2
		try:
		    os.system(cmd)
		except:
			err('orio.module.chill.chill:  failed to run command: %s' % cmd)


	#CLEAN THE WORKING DIRECTORY
	if recipeFound == False:
		cname = 'recipe'+tag+'.lua'
		cmd = 'rm '+cname
		try:
		    os.system(cmd)
		except:
	            err('orio.module.chill.chill:  failed to run command: %s' % cmd)

		cmd = 'rm rose_'+fname+'u'
		try:
		    os.system(cmd)
		except:
	            err('orio.module.chill.chill:  failed to run command: %s' % cmd)


        # Do nothing except output the code annotated with a comment for the parameters that were specified
        # TODO: this is where we use the provided CHiLL recipe or generate a new one
        # Then invoke CHiLL to produce the output_code
	
	## We annotate which recipe file was used to generate this version
	output_code = '\n\n //Testing with file: ' + cname
	output_code = output_code + '\n //Output file is: ' +fname2


        output_code = output_code + '\n\n#include \"_orio_chill_.h\" \n\n'
	output_code = output_code + func2 + '\n\n'

        # return the output code
        return output_code
